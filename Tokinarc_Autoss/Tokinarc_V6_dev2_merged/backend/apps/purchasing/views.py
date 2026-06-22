from __future__ import annotations

from django.db.models import F, Sum
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.accounts.roles import (
    INTERNAL_ROLES, MANAGER_ROLES, WMS_OP_ROLES, role_of,
)
from apps.common.models import AuditLog
from apps.wms import services as wms_services

from .models import PurchaseOrder, PurchasePayment, PurchaseStatus, Supplier
from .serializers import (
    PurchaseOrderSerializer, PurchasePaymentSerializer, SupplierSerializer,
)


class PurchasingPermission(permissions.BasePermission):
    """Đọc: nhân viên nội bộ. Ghi (tạo/sửa PO, NCC, thanh toán): manager/CEO/admin."""
    message = "Bạn không có quyền với phân hệ Mua hàng."

    def has_permission(self, request, view):
        r = role_of(request.user) if request.user.is_authenticated else None
        if not r or r not in INTERNAL_ROLES:
            return False
        if request.method in SAFE_METHODS:
            return True
        # Nhận hàng theo PO: cho phép vai trò kho (kiểm tra kỹ trong action).
        if getattr(view, 'action', None) == 'receive':
            return r in WMS_OP_ROLES
        return r in MANAGER_ROLES


class SupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [PurchasingPermission]
    queryset = Supplier.objects.all()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    serializer_class = PurchaseOrderSerializer
    permission_classes = [PurchasingPermission]
    queryset = PurchaseOrder.objects.select_related('supplier', 'warehouse', 'owner').prefetch_related('lines')

    def perform_create(self, serializer):
        year = timezone.now().year
        pre = f'PO-{year}-'
        last = PurchaseOrder.objects.filter(code__startswith=pre).order_by('-code').first()
        seq = (int(last.code.rsplit('-', 1)[-1]) + 1) if last else 1
        po = serializer.save(code=f'{pre}{seq:03d}', owner=self.request.user,
                             created_by=self.request.user, updated_by=self.request.user)
        AuditLog.record(user=self.request.user, action='create', entity='pur.PurchaseOrder',
                        entity_id=po.id, diff={'code': po.code})

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Đặt hàng: draft → ordered."""
        po = self.get_object()
        if po.status != PurchaseStatus.DRAFT:
            return Response({'detail': 'Chỉ đặt được đơn nháp.', 'code': 'CONFLICT'}, status=409)
        po.status = PurchaseStatus.ORDERED
        po.order_date = po.order_date or timezone.now().date()
        po.save(update_fields=['status', 'order_date'])
        return Response(PurchaseOrderSerializer(po).data)

    @action(detail=True, methods=['post'])
    def receive(self, request, pk=None):
        """Nhận hàng theo PO → cộng tồn (warehouse roles). Có thể nhận từng phần.

        Body (tùy chọn): {lines: [{line_id, qty}]}. Bỏ trống = nhận hết phần còn lại.
        """
        if role_of(request.user) not in WMS_OP_ROLES:
            return Response({'detail': 'Cần quyền kho để nhận hàng.'}, status=403)
        po = self.get_object()
        if po.status not in (PurchaseStatus.ORDERED, PurchaseStatus.PARTIAL):
            return Response({'detail': 'Đơn chưa đặt hoặc đã nhận đủ.', 'code': 'CONFLICT'}, status=409)

        from apps.wms.models import Bin
        want = {str(x['line_id']): int(x['qty']) for x in request.data.get('lines', [])}
        default_bin = Bin.objects.filter(zone__warehouse=po.warehouse).first()
        received_any = False
        for line in po.lines.all():
            remaining = line.qty - line.qty_received
            take = want.get(str(line.id), remaining) if want else remaining
            take = min(max(0, take), remaining)
            if take <= 0:
                continue
            bin_obj = line.target_bin or default_bin
            if bin_obj is None:
                return Response({'detail': f'Kho {po.warehouse.code} chưa có ô (bin) để nhận.'}, status=400)
            wms_services.receive_stock(bin_obj=bin_obj, part=line.part, qty=take,
                                       user=request.user, ref_id=po.code)
            line.qty_received += take
            line.save(update_fields=['qty_received'])
            received_any = True
        if not received_any:
            return Response({'detail': 'Không có dòng nào để nhận.'}, status=400)
        done = all(l.qty_received >= l.qty for l in po.lines.all())
        po.status = PurchaseStatus.RECEIVED if done else PurchaseStatus.PARTIAL
        if done:
            po.received_at = timezone.now()
        po.save(update_fields=['status', 'received_at'])
        return Response(PurchaseOrderSerializer(po).data)

    @action(detail=False, methods=['get'], url_path='ap-summary')
    def ap_summary(self, request):
        """Công nợ phải trả theo nhà cung cấp."""
        qs = (PurchaseOrder.objects
              .filter(status__in=['ordered', 'partial', 'received'], total_vnd__gt=F('paid_vnd'))
              .values('supplier__name')
              .annotate(debt=Sum(F('total_vnd') - F('paid_vnd'))).order_by('-debt'))
        total = sum(r['debt'] for r in qs)
        return Response({'total_payable': int(total),
                         'by_supplier': [{'supplier': r['supplier__name'], 'debt': int(r['debt'])} for r in qs]})


class PurchasePaymentViewSet(viewsets.ModelViewSet):
    serializer_class = PurchasePaymentSerializer
    permission_classes = [PurchasingPermission]
    queryset = PurchasePayment.objects.select_related('po')

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        po = ser.validated_data['po']
        amount = ser.validated_data['amount_vnd']
        if amount <= 0:
            return Response({'detail': 'Số tiền phải > 0.'}, status=400)
        if po.paid_vnd + amount > po.total_vnd:
            return Response({'detail': 'Thanh toán vượt quá giá trị đơn mua.'}, status=400)
        p = ser.save(created_by=request.user, updated_by=request.user)
        PurchaseOrder.objects.filter(pk=po.pk).update(paid_vnd=F('paid_vnd') + amount)
        return Response(PurchasePaymentSerializer(p).data, status=201)

    @action(detail=False, methods=['get'], url_path='export-misa')
    def export_misa(self, request):
        """Xuất Excel phiếu CHI (AP) trả NCC để nạp vào MISA. ?from=&to=."""
        import io

        from django.http import HttpResponse
        from openpyxl import Workbook
        qs = PurchasePayment.objects.select_related('po', 'po__supplier').order_by('-paid_at')
        if request.query_params.get('from'):
            qs = qs.filter(paid_at__gte=request.query_params['from'])
        if request.query_params.get('to'):
            qs = qs.filter(paid_at__lte=request.query_params['to'])
        wb = Workbook(); ws = wb.active; ws.title = 'PhieuChi_MISA'
        ws.append(['Ngay', 'Don mua', 'Ma NCC', 'Ten NCC', 'So tien', 'Hinh thuc', 'Tham chieu'])
        for p in qs:
            ws.append([p.paid_at.isoformat(), p.po.code, p.po.supplier.code,
                       p.po.supplier.name, int(p.amount_vnd), p.method, p.reference])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        resp = HttpResponse(buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = 'attachment; filename="phieuchi_misa.xlsx"'
        return resp
