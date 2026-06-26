from __future__ import annotations

from django.db.models import F, Sum
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.accounts.roles import (
    CEO_ROLES, INTERNAL_ROLES, MANAGER_ROLES, WMS_OP_ROLES, Role,
    is_ceo, is_manager, role_of,
)
from apps.common.models import AuditLog, notify, notify_roles
from apps.wms import services as wms_services

# Nhân viên kho (NV kho + quản lý kho) — nhận noti "đơn mua đã duyệt, hàng sắp về".
WAREHOUSE_STAFF = frozenset({Role.WAREHOUSE, Role.WAREHOUSE_MANAGER})

from .models import PurchaseOrder, PurchasePayment, PurchaseStatus, Supplier
from .serializers import (
    PurchaseOrderSerializer, PurchasePaymentSerializer, SupplierSerializer,
)


PO_WRITE_ROLES = MANAGER_ROLES | {Role.WAREHOUSE_MANAGER}   # QL kho lập đơn mua (Mua hàng ở tab WMS)


class PurchasingPermission(permissions.BasePermission):
    """Đọc: nhân viên nội bộ. Tạo/sửa PO+NCC: QL kho + manager/CEO/admin.
    Duyệt: kiểm tra is_manager/is_ceo trong từng action (CEO duyệt đơn mua)."""
    message = "Bạn không có quyền với phân hệ Mua hàng."

    def has_permission(self, request, view):
        r = role_of(request.user) if request.user.is_authenticated else None
        if not r or r not in INTERNAL_ROLES:
            return False
        action = getattr(view, 'action', None)
        if request.method in SAFE_METHODS:
            # Nhân viên kho THUẦN không xem danh sách Mua hàng / NCC (việc của QL kho trở lên);
            # vẫn cho xem chi tiết 1 PO (retrieve) để phục vụ nhận hàng.
            if r in PO_WRITE_ROLES:
                return True
            return action == 'retrieve' and r in WMS_OP_ROLES
        # Nhận hàng theo PO: cho phép vai trò kho (kiểm tra kỹ trong action).
        if action == 'receive':
            return r in WMS_OP_ROLES
        return r in PO_WRITE_ROLES


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
        # Báo manager+: có đơn mua mới cần duyệt (trừ người tạo).
        notify_roles(MANAGER_ROLES, 'po_approval',
                     f"Đơn mua {po.code} ({po.supplier.name}) cần duyệt.",
                     link='/ceo/approvals', exclude_user=self.request.user)

    def _finalize_approved(self, po, request):
        """Hoàn tất duyệt → APPROVED; báo người tạo + nhân viên kho (hàng sắp về)."""
        po.approved_by = request.user
        po.status = PurchaseStatus.APPROVED
        po.save(update_fields=['status', 'approved_by', 'updated_at'])
        notify(po.owner, 'po_approved',
               f"Đơn mua {po.code} đã được duyệt — có thể đặt hàng.", link='/purchasing/orders')
        notify_roles(WAREHOUSE_STAFF, 'po_approved',
                     f"Đơn mua {po.code} ({po.supplier.name}) đã duyệt — hàng sắp về, chuẩn bị nhận.",
                     link='/wms/inbound')

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Duyệt cấp 1 (manager/CEO/admin). Vượt ngưỡng → chờ CEO duyệt cấp 2."""
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý/CEO/admin được duyệt đơn mua.'}, status=403)
        po = self.get_object()
        if po.status != PurchaseStatus.DRAFT:
            return Response({'detail': 'Chỉ duyệt được đơn ở trạng thái nháp.', 'code': 'CONFLICT'}, status=409)
        now = timezone.now()
        po.l1_approved_by = request.user
        po.l1_approved_at = now
        if po.requires_l2():
            po.status = PurchaseStatus.PENDING_CEO
            po.save(update_fields=['status', 'l1_approved_by', 'l1_approved_at', 'updated_at'])
            notify_roles(CEO_ROLES, 'po_approval',
                         f"Đơn mua {po.code} ({po.supplier.name}) chờ CEO duyệt cấp 2.",
                         link='/ceo/approvals')
            AuditLog.record(user=request.user, action='approve_l1', entity='pur.PurchaseOrder',
                            entity_id=po.id, diff={'next': 'pending_ceo'})
        else:
            po.save(update_fields=['l1_approved_by', 'l1_approved_at', 'updated_at'])
            self._finalize_approved(po, request)
            AuditLog.record(user=request.user, action='approve', entity='pur.PurchaseOrder',
                            entity_id=po.id, diff={'level': 1})
        return Response(PurchaseOrderSerializer(po).data)

    @action(detail=True, methods=['post'], url_path='approve-l2')
    def approve_l2(self, request, pk=None):
        """Duyệt cấp 2 (CEO/admin) cho đơn mua vượt ngưỡng đang chờ."""
        po = self.get_object()
        if not is_ceo(request.user):
            return Response({'detail': 'Chỉ CEO/admin được duyệt cấp 2.'}, status=403)
        if po.status != PurchaseStatus.PENDING_CEO:
            return Response({'detail': f'Đơn mua ở trạng thái {po.status}, không chờ CEO duyệt.',
                             'code': 'CONFLICT'}, status=409)
        if role_of(request.user) != 'admin' and request.user.id in (po.owner_id, po.l1_approved_by_id):
            return Response({'detail': 'Không thể tự duyệt cấp 2 đơn mình tạo/đã duyệt cấp 1.'}, status=403)
        po.l2_approved_by = request.user
        po.l2_approved_at = timezone.now()
        po.save(update_fields=['l2_approved_by', 'l2_approved_at', 'updated_at'])
        self._finalize_approved(po, request)
        AuditLog.record(user=request.user, action='approve', entity='pur.PurchaseOrder',
                        entity_id=po.id, diff={'level': 2})
        return Response(PurchaseOrderSerializer(po).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Từ chối đơn mua (manager+) kèm lý do; báo người tạo."""
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý/CEO/admin được từ chối.'}, status=403)
        po = self.get_object()
        if po.status not in (PurchaseStatus.DRAFT, PurchaseStatus.PENDING_CEO):
            return Response({'detail': 'Chỉ từ chối được đơn đang chờ duyệt.', 'code': 'CONFLICT'}, status=409)
        reason = str(request.data.get('reason', '')).strip()
        po.status = PurchaseStatus.REJECTED
        if reason:
            po.notes = (po.notes + f'\n[Từ chối] {reason}').strip()
        po.save(update_fields=['status', 'notes', 'updated_at'])
        notify(po.owner, 'po_rejected',
               f"Đơn mua {po.code} bị từ chối. {reason}".strip(), link='/purchasing/orders')
        AuditLog.record(user=request.user, action='reject', entity='pur.PurchaseOrder',
                        entity_id=po.id, diff={'reason': reason})
        return Response(PurchaseOrderSerializer(po).data)

    @action(detail=False, methods=['get'], url_path='pending-approvals')
    def pending_approvals(self, request):
        """Đơn mua đang chờ duyệt cho trang Duyệt tập trung (manager+ thấy tất cả)."""
        qs = (self.get_queryset()
              .filter(status__in=[PurchaseStatus.DRAFT, PurchaseStatus.PENDING_CEO])
              .order_by('-created_at'))
        return Response({'results': PurchaseOrderSerializer(qs, many=True).data, 'count': qs.count()})

    @action(detail=True, methods=['get'], url_path='export-xlsx')
    def export_xlsx(self, request, pk=None):
        """Xuất đề xuất/đơn mua ra Excel (đầu trang NCC + bảng dòng + ô duyệt)."""
        from apps.common.company import vnd_to_words
        from apps.common.excel import make_document_xlsx, supplier_party, xlsx_response
        po = self.get_object()
        rows = [(l.part_id, getattr(l.part, 'display_name_vi', '') or '', l.qty,
                 int(l.unit_cost or 0), int(l.line_total or 0)) for l in po.lines.all()]
        data = make_document_xlsx(
            sheet_title='DonMua', doc_title='ĐỀ XUẤT / ĐƠN MUA HÀNG', doc_code=po.code,
            doc_date=po.created_at.strftime('%d/%m/%Y'),
            party_label='NHÀ CUNG CẤP:', party=supplier_party(po.supplier),
            meta=[('Kho nhận:', po.warehouse.code),
                  ('Người đề xuất:', po.owner.username if po.owner_id else '—'),
                  ('Trạng thái:', po.get_status_display())],
            columns=[('Mã part', 16, 'text'), ('Tên hàng', 40, 'text'), ('SL', 8, 'int'),
                     ('Đơn giá', 16, 'money'), ('Thành tiền', 18, 'money')],
            rows=rows, total_label='TỔNG CỘNG', total_value=int(po.total_vnd or 0),
            amount_words=vnd_to_words(po.total_vnd),
            signatures=['NGƯỜI ĐỀ XUẤT', 'DUYỆT CẤP 1 (QL)', 'DUYỆT CẤP 2 (CEO)'])
        return xlsx_response(data, f'don_mua_{po.code}.xlsx')

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Đặt hàng: approved → ordered (chỉ sau khi đã duyệt)."""
        po = self.get_object()
        if po.status != PurchaseStatus.APPROVED:
            return Response({'detail': 'Chỉ đặt được đơn đã duyệt.', 'code': 'CONFLICT'}, status=409)
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
            # Kết chuyển giá vốn bình quân (WAC) từ giá mua thực của dòng.
            from apps.catalog.costing import update_wac
            update_wac(line.part, take, line.unit_cost)
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

    @action(detail=False, methods=['get'], url_path='incoming')
    def incoming(self, request):
        """Hàng đang về: đơn ĐÃ ĐẶT / NHẬN MỘT PHẦN, sắp theo ngày dự kiến; đánh dấu TRỄ."""
        from datetime import date
        today = date.today()
        qs = (PurchaseOrder.objects.filter(status__in=['ordered', 'partial'])
              .select_related('supplier')
              .order_by(F('expected_date').asc(nulls_last=True), 'created_at'))
        results, overdue = [], 0
        for po in qs:
            late = (today - po.expected_date).days if (po.expected_date and po.expected_date < today) else 0
            if late > 0:
                overdue += 1
            results.append({
                'id': str(po.id), 'code': po.code, 'supplier_name': po.supplier.name,
                'status': po.status, 'status_display': po.get_status_display(),
                'expected_date': po.expected_date.isoformat() if po.expected_date else None,
                'carrier': po.carrier, 'tracking_no': po.tracking_no,
                'total_vnd': int(po.total_vnd or 0), 'days_late': late, 'is_overdue': late > 0,
            })
        return Response({'count': len(results), 'overdue': overdue, 'results': results})


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
        ws.append(['Ngay', 'Don mua', 'Ma NCC', 'Ten NCC', 'MST', 'Dien thoai', 'Dia chi',
                   'So tien', 'Hinh thuc', 'Tham chieu'])
        for p in qs:
            s = p.po.supplier
            ws.append([p.paid_at.isoformat(), p.po.code, s.code, s.name,
                       s.tax_code or '', s.phone or '', s.address or '',
                       int(p.amount_vnd), p.method, p.reference])
        from apps.common.excel import style_table_sheet
        style_table_sheet(ws, widths=[12, 14, 10, 28, 14, 14, 36, 14, 12, 16])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        resp = HttpResponse(buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = 'attachment; filename="phieuchi_misa.xlsx"'
        return resp
