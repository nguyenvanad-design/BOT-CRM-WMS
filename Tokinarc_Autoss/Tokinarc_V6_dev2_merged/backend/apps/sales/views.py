"""
Tokinarc V6.C — apps/sales/views.py — khớp V6.B.3 §3.4
"""
from __future__ import annotations

from django.db.models import F, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.roles import Role, is_manager
from apps.common.models import AuditLog, notify_roles

# Nhân viên kho (NV kho + quản lý kho) — nhận noti "có việc kho mới".
WAREHOUSE_STAFF = frozenset({Role.WAREHOUSE, Role.WAREHOUSE_MANAGER})

from . import services
from .models import Invoice, Payment, SalesOrder
from .permissions import SalesPermission, role_of  # noqa: F401 (role_of dùng nơi khác)
from .serializers import (
    InvoiceSerializer, PaymentSerializer, ReturnOrderSerializer,
    SalesOrderDetailSerializer, SalesOrderListSerializer,
)


def _publish(channel, payload):
    try:
        from tokinarc.eventbus.publisher import publish
        publish(channel, payload)
    except Exception:
        pass


def _customer_contact_addr(cust):
    """Trả (SĐT người liên hệ chính, địa chỉ chuỗi) của KH — cho xuất Excel."""
    addr = cust.address if isinstance(cust.address, dict) else {}
    address = ', '.join(x for x in [addr.get('street'), addr.get('district'),
                                    addr.get('city')] if x)
    pc = cust.contacts.filter(is_primary=True).first() or cust.contacts.first()
    return (pc.phone if pc else ''), address


def _create_outbound_for_order(order, user) -> str | None:
    """Khi ship đơn → tự tạo WMS OutboundOrder (draft) gắn sales_order_code.
    Trả mã phiếu xuất, hoặc None nếu không có kho mặc định / đã có phiếu."""
    from apps.catalog.models import Part
    from apps.wms.models import OutboundLine, OutboundOrder, Warehouse

    if OutboundOrder.objects.filter(sales_order_code=order.code).exists():
        return None
    actives = Warehouse.objects.filter(is_active=True)
    wh = actives.first() if actives.count() == 1 else actives.filter(is_default=True).first()
    if wh is None:
        return None
    year = timezone.now().year
    pre = f'OUT-{year}-'
    last = OutboundOrder.objects.filter(code__startswith=pre).order_by('-code').first()
    seq = (int(last.code.rsplit('-', 1)[-1]) + 1) if last else 1
    code = f'{pre}{seq:03d}'
    ob = OutboundOrder.objects.create(
        code=code, warehouse=wh, sales_order_code=order.code, customer=order.customer,
        created_by=user, updated_by=user,
    )
    for idx, ol in enumerate(order.lines.all()):
        if ol.part_id:
            OutboundLine.objects.create(
                outbound=ob, part=Part.objects.filter(pk=ol.part_id).first(),
                qty_ordered=ol.qty, order_idx=idx)
    # Báo nhân viên kho: có phiếu xuất mới cần soạn/giao hàng.
    notify_roles(WAREHOUSE_STAFF, 'outbound_created',
                 f"Phiếu xuất {code} cần soạn hàng cho KH {order.customer.name}.",
                 link='/wms/outbound')
    return code


class SalesOrderViewSet(viewsets.ModelViewSet):
    permission_classes = [SalesPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'order_type', 'customer', 'owner']
    search_fields = ['code', 'customer__name']
    ordering_fields = ['issued_date', 'total_vnd', 'created_at']

    def get_queryset(self):
        qs = (SalesOrder.objects.select_related('customer', 'owner')
              .prefetch_related('lines')
              .annotate(debt_vnd=F('total_vnd') - F('paid_vnd')))
        if not is_manager(self.request.user):
            qs = qs.filter(owner_id=self.request.user.id)
        return qs

    def get_serializer_class(self):
        return SalesOrderListSerializer if self.action == 'list' else SalesOrderDetailSerializer

    def perform_create(self, serializer):
        owner = serializer.validated_data.get('owner') or self.request.user
        if not is_manager(self.request.user):
            owner = self.request.user
        order = serializer.save(owner=owner, created_by=self.request.user,
                                updated_by=self.request.user)
        AuditLog.record(user=self.request.user, action='create', entity='sales.SalesOrder',
                        entity_id=order.id, diff={'code': order.code})

    @action(detail=True, methods=['post'])
    def sign(self, request, pk=None):
        order = self.get_object()
        if order.status not in ('draft', 'pending'):
            return Response({'detail': 'Chỉ ký được đơn nháp/chờ ký.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        order.status = 'active'
        order.save(update_fields=['status'])
        AuditLog.record(user=request.user, action='sign', entity='sales.SalesOrder',
                        entity_id=order.id)
        return Response(SalesOrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'])
    def ship(self, request, pk=None):
        order = self.get_object()
        if order.status != 'active':
            return Response({'detail': 'Đơn chưa hiệu lực.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        order.status = 'shipping'
        order.save(update_fields=['status'])
        outbound_code = _create_outbound_for_order(order, request.user)
        from tokinarc.eventbus.channels import Channel
        _publish(Channel.ORDER_SHIPPED, {'order': order.code, 'customer_id': str(order.customer_id),
                                         'outbound': outbound_code})
        data = SalesOrderDetailSerializer(order).data
        data['outbound_code'] = outbound_code
        return Response(data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        if order.status in ('completed', 'cancelled'):
            return Response({'detail': 'Không thể hủy.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        order.status = 'cancelled'
        order.save(update_fields=['status'])
        return Response(SalesOrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'])
    def amend(self, request, pk=None):
        """Sửa đơn SAU KÝ (đổi địa chỉ giao / SL dòng / ghi chú) — có audit.
        Chỉ khi đơn CHƯA giao (draft/pending/active). Manager+ thực hiện."""
        from decimal import Decimal

        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý/CEO/admin sửa đơn.'}, status=403)
        order = self.get_object()
        if order.status not in ('draft', 'pending', 'active'):
            return Response({'detail': 'Đơn đang/đã giao — không sửa được. Dùng RMA nếu cần.',
                             'code': 'CONFLICT'}, status=status.HTTP_409_CONFLICT)
        diff = {}
        if 'ship_address' in request.data:
            order.ship_address = str(request.data['ship_address']).strip()
            diff['ship_address'] = order.ship_address
        if 'notes' in request.data:
            order.notes = str(request.data['notes']).strip()
            diff['notes'] = order.notes
        # Sửa số lượng từng dòng (không nhỏ hơn đã giao).
        line_edits = {str(x.get('id')): x for x in (request.data.get('lines') or [])}
        if line_edits:
            for ln in order.lines.all():
                e = line_edits.get(str(ln.id))
                if not e or 'qty' not in e:
                    continue
                new_qty = int(e['qty'])
                if new_qty < ln.shipped_qty:
                    return Response({'detail': f'Dòng {ln.description}: SL {new_qty} < đã giao '
                                     f'{ln.shipped_qty}.', 'code': 'CONFLICT'}, status=409)
                unit = Decimal(ln.unit_price) * (Decimal('100') - Decimal(ln.discount_pct)) / 100
                ln.qty = new_qty
                ln.line_total = (unit * new_qty).quantize(Decimal('1'))
                ln.save(update_fields=['qty', 'line_total'])
                diff[f'line:{ln.id}'] = new_qty
            order.total_vnd = sum((l.line_total for l in order.lines.all()), Decimal('0'))
        order.save()
        AuditLog.record(user=request.user, action='amend', entity='sales.SalesOrder',
                        entity_id=order.id, diff=diff)
        return Response(SalesOrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'], url_path='create-invoice')
    def create_invoice(self, request, pk=None):
        """Xuất hóa đơn VAT từ đơn bán. Body tùy chọn {tax_pct} (mặc định 8%)."""
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý/CEO/admin xuất hóa đơn.'}, status=403)
        order = self.get_object()
        if order.status in ('draft', 'cancelled'):
            return Response({'detail': 'Đơn chưa hiệu lực, không xuất hóa đơn.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        from decimal import Decimal
        try:
            tax_pct = Decimal(str(request.data.get('tax_pct', 8)))
        except Exception:  # noqa: BLE001
            tax_pct = Decimal('8')
        year = timezone.now().year
        pre = f'INV-{year}-'
        last = Invoice.objects.filter(code__startswith=pre).order_by('-code').first()
        seq = (int(last.code.rsplit('-', 1)[-1]) + 1) if last else 1
        subtotal = order.total_vnd or 0
        tax = (subtotal * tax_pct / 100).quantize(Decimal('1'))
        inv = Invoice.objects.create(
            code=f'{pre}{seq:03d}', order=order, customer=order.customer,
            issue_date=timezone.now().date(), subtotal_vnd=subtotal, tax_pct=tax_pct,
            tax_vnd=tax, total_vnd=subtotal + tax, created_by=request.user, updated_by=request.user)
        AuditLog.record(user=request.user, action='create', entity='sales.Invoice',
                        entity_id=inv.id, diff={'code': inv.code})
        return Response(InvoiceSerializer(inv).data, status=201)

    @action(detail=False, methods=['get'], url_path='debt-aging')
    def debt_aging(self, request):
        qs = (self.get_queryset()
              .filter(status__in=['active', 'shipping', 'completed'], total_vnd__gt=F('paid_vnd')))
        data = [{'code': o.code, 'customer': o.customer.name,
                 'amount_due': o.total_vnd - o.paid_vnd,
                 'issued_date': o.issued_date} for o in qs]
        return Response({'count': len(data), 'results': data})

    @action(detail=False, methods=['get'])
    def summary(self, request):
        qs = self.get_queryset()
        agg = qs.aggregate(total=Sum('total_vnd'), paid=Sum('paid_vnd'))
        total = agg['total'] or 0
        paid = agg['paid'] or 0
        return Response({'total_vnd': total, 'paid_vnd': paid, 'debt_vnd': total - paid,
                         'order_count': qs.count()})


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.select_related('order')
    serializer_class = PaymentSerializer
    permission_classes = [SalesPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['order', 'method']

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = ser.validated_data['order']
        try:
            p = services.record_payment(
                order, amount=ser.validated_data['amount_vnd'],
                paid_at=ser.validated_data['paid_at'],
                method=ser.validated_data['method'],
                reference=ser.validated_data.get('reference', ''), user=request.user)
        except ValueError as e:
            return Response({'detail': str(e), 'code': 'VALIDATION_FAILED'},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(PaymentSerializer(p).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='export-misa')
    def export_misa(self, request):
        """Xuất Excel phiếu THU (AR) để nạp vào MISA. ?from=&to= (ngày)."""
        import io

        from django.http import HttpResponse
        from openpyxl import Workbook
        qs = Payment.objects.select_related('order', 'order__customer').order_by('-paid_at')
        if request.query_params.get('from'):
            qs = qs.filter(paid_at__gte=request.query_params['from'])
        if request.query_params.get('to'):
            qs = qs.filter(paid_at__lte=request.query_params['to'])
        wb = Workbook(); ws = wb.active; ws.title = 'PhieuThu_MISA'
        ws.append(['Ngay', 'Don hang', 'Ma KH', 'Ten KH', 'MST', 'Dien thoai', 'Dia chi',
                   'So tien', 'Hinh thuc', 'Tham chieu'])
        for p in qs:
            cust = p.order.customer
            phone, address = _customer_contact_addr(cust)
            ws.append([p.paid_at.isoformat(), p.order.code, cust.code, cust.name,
                       cust.tax_code or '', phone, address,
                       int(p.amount_vnd), p.method, p.reference])
        from apps.common.excel import style_table_sheet
        style_table_sheet(ws, widths=[12, 14, 10, 28, 14, 14, 36, 14, 12, 16])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        resp = HttpResponse(buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = 'attachment; filename="phieuthu_misa.xlsx"'
        return resp


class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """Đề nghị xuất hóa đơn (đọc). Tạo qua /orders/{id}/create-invoice/.
    Tích hợp MISA: export-misa (lấy dữ liệu đẩy sang MISA) + mark-synced."""
    serializer_class = InvoiceSerializer
    permission_classes = [SalesPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['order', 'customer', 'status', 'misa_status']

    def get_queryset(self):
        qs = Invoice.objects.select_related('order', 'customer')
        if not is_manager(self.request.user):
            qs = qs.filter(order__owner_id=self.request.user.id)
        return qs

    @action(detail=False, methods=['get'], url_path='export-misa')
    def export_misa(self, request):
        """Xuất Excel hóa đơn CHƯA đồng bộ để nạp vào MISA (?all=1 lấy tất cả)."""
        import io

        from django.http import HttpResponse
        from openpyxl import Workbook
        qs = self.get_queryset()
        if request.query_params.get('all') != '1':
            qs = qs.filter(misa_status='pending')
        wb = Workbook(); ws = wb.active; ws.title = 'HoaDon_MISA'
        ws.append(['Ma de nghi', 'Ngay', 'Ma KH', 'Ten KH', 'MST', 'Dien thoai', 'Dia chi',
                   'Don hang', 'Tien hang', 'Thue %', 'Tien thue', 'Tong cong'])
        for inv in qs.select_related('customer', 'order'):
            phone, address = _customer_contact_addr(inv.customer)
            ws.append([inv.code, inv.issue_date.isoformat(), inv.customer.code,
                       inv.customer.name, inv.customer.tax_code or '', phone, address,
                       inv.order.code, int(inv.subtotal_vnd), float(inv.tax_pct),
                       int(inv.tax_vnd), int(inv.total_vnd)])
        from apps.common.excel import style_table_sheet
        style_table_sheet(ws, widths=[14, 12, 10, 28, 14, 14, 36, 14, 14, 8, 14, 16])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        resp = HttpResponse(buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = 'attachment; filename="hoadon_misa.xlsx"'
        return resp

    @action(detail=True, methods=['post'], url_path='mark-synced')
    def mark_synced(self, request, pk=None):
        """Đánh dấu đã đẩy/đối soát với MISA + lưu số hóa đơn MISA trả về."""
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý/CEO/admin.'}, status=403)
        inv = self.get_object()
        inv.misa_status = 'synced'
        inv.misa_ref = (request.data.get('misa_ref') or '').strip()
        inv.synced_at = timezone.now()
        inv.save(update_fields=['misa_status', 'misa_ref', 'synced_at'])
        return Response(InvoiceSerializer(inv).data)


class ReturnOrderViewSet(viewsets.ModelViewSet):
    """Trả hàng (RMA): tạo → nhận lại kho (+tồn, reason=return). Hoàn tiền do MISA."""
    serializer_class = ReturnOrderSerializer
    permission_classes = [SalesPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'customer', 'order']

    def get_queryset(self):
        from apps.accounts.roles import WMS_OP_ROLES, role_of
        from .models import ReturnOrder
        qs = ReturnOrder.objects.select_related('customer', 'warehouse', 'owner').prefetch_related('lines')
        # Vai trò kho cần thấy mọi phiếu để nhận lại; sale chỉ thấy của mình.
        if not is_manager(self.request.user) and role_of(self.request.user) not in WMS_OP_ROLES:
            qs = qs.filter(owner_id=self.request.user.id)
        return qs

    def perform_create(self, serializer):
        from .models import ReturnOrder
        year = timezone.now().year
        pre = f'RMA-{year}-'
        last = ReturnOrder.objects.filter(code__startswith=pre).order_by('-code').first()
        seq = (int(last.code.rsplit('-', 1)[-1]) + 1) if last else 1
        serializer.save(code=f'{pre}{seq:03d}', owner=self.request.user,
                        created_by=self.request.user, updated_by=self.request.user)

    @action(detail=True, methods=['post'])
    def receive(self, request, pk=None):
        """Nhận hàng trả về kho → +tồn (movement reason=return). Vai trò kho."""
        from apps.accounts.roles import WMS_OP_ROLES, role_of
        from apps.wms.models import Bin
        from apps.wms.models import MovementReason
        from apps.wms import services as wms_services
        from .models import ReturnStatus
        if role_of(request.user) not in WMS_OP_ROLES:
            return Response({'detail': 'Cần quyền kho để nhận hàng trả.'}, status=403)
        ro = self.get_object()
        if ro.status != ReturnStatus.DRAFT:
            return Response({'detail': 'Phiếu trả đã xử lý.', 'code': 'CONFLICT'}, status=409)
        default_bin = Bin.objects.filter(zone__warehouse=ro.warehouse).first()
        for line in ro.lines.all():
            bin_obj = line.target_bin or default_bin
            if bin_obj is None:
                return Response({'detail': f'Kho {ro.warehouse.code} chưa có ô để nhận.'}, status=400)
            wms_services.receive_stock(bin_obj=bin_obj, part=line.part, qty=line.qty,
                                       user=request.user, ref_id=ro.code,
                                       reason=MovementReason.RETURN, ref_kind='return')
        ro.status = ReturnStatus.RECEIVED
        ro.received_at = timezone.now()
        ro.save(update_fields=['status', 'received_at'])
        from .serializers import ReturnOrderSerializer
        return Response(ReturnOrderSerializer(ro).data)
