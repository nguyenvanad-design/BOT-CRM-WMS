"""
Tokinarc V6.C — apps/wms/views.py

ViewSets khớp V6.B.3 §3.5. Điểm cốt lõi multi-warehouse:
  - Mọi endpoint nhận ?warehouse=<code> để lọc.
  - Nếu bỏ trống và hệ thống chỉ 1 kho active → auto kho đó (helper resolve_warehouse).
  - Stock mutation đi qua services.py (concurrency-safe + ghi StockMovement).

Event bus (B.1 §5): các action arrive/ship publish LISTEN/NOTIFY. Ở đây gọi
publish() placeholder — nối vào tokinarc.eventbus.publisher khi có.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import F, ProtectedError
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import Count, Sum
from django.db.models.functions import Abs

from apps.accounts.roles import MANAGER_ROLES, Role, is_wms_control
from apps.catalog.models import Part, Torch
from apps.common.models import notify_roles

# Ngưỡng điều chỉnh tồn coi là "lớn" → báo quản lý giám sát.
ADJUST_NOTIFY_QTY = 5

# Nhân viên kho (NV kho + quản lý kho) — nhận noti "có việc kho mới".
WAREHOUSE_STAFF = frozenset({Role.WAREHOUSE, Role.WAREHOUSE_MANAGER})

from . import services
from .models import (
    ASN, Bin, CycleCount, CycleCountLine, InboundOrder, InventoryItem, Lot,
    OutboundOrder, SerialNumber, StockMovement, Warehouse, Zone,
)
from .permissions import WMSPermission, WmsControlAccess
from .serializers import (
    ASNSerializer, AdjustSerializer, BinSerializer, InboundOrderSerializer,
    InventoryItemSerializer, LotSerializer, OutboundOrderSerializer,
    PickListItemSerializer, SerialNumberSerializer, StockMovementSerializer,
    TransferSerializer, WarehouseSerializer, ZoneSerializer,
)


def resolve_warehouse(request) -> Warehouse | None:
    """
    Lấy warehouse từ ?warehouse=<code>. Nếu trống và chỉ 1 kho active → auto.
    Trả None nếu nhiều kho mà không chỉ định (caller quyết xử lý).
    """
    code = request.query_params.get('warehouse')
    if code:
        try:
            return Warehouse.objects.get(code=code, is_active=True)
        except Warehouse.DoesNotExist:
            raise ValidationError({'warehouse': f"Không có kho '{code}'."})
    actives = Warehouse.objects.filter(is_active=True)
    if actives.count() == 1:
        return actives.first()
    default = actives.filter(is_default=True).first()
    return default   # có thể None nếu nhiều kho, không default


def _publish(channel: str, payload: dict):
    """Placeholder — nối vào tokinarc.eventbus.publisher.publish khi sẵn sàng."""
    try:
        from tokinarc.eventbus.publisher import publish
        publish(channel, payload)
    except Exception:
        pass   # event bus optional ở giai đoạn đầu


class WarehouseViewSet(viewsets.ModelViewSet):
    """Quản lý kho. Đọc: nội bộ. Tạo/sửa: QL kho trở lên.
    FE cũng đọc để quyết hiện/ẩn switcher (ẩn khi count==1)."""
    queryset = Warehouse.objects.all().order_by('-is_default', 'code')
    serializer_class = WarehouseSerializer
    permission_classes = [WmsControlAccess]

    def _keep_single_default(self, obj):
        if obj.is_default:
            Warehouse.objects.exclude(pk=obj.pk).filter(is_default=True).update(is_default=False)

    def perform_create(self, serializer):
        self._keep_single_default(serializer.save())

    def perform_update(self, serializer):
        self._keep_single_default(serializer.save())

    def destroy(self, request, *args, **kwargs):
        wh = self.get_object()
        n = wh.zones.count()
        if n:
            return Response({'detail': f'Kho còn {n} khu — xoá hết khu trước khi xoá kho.',
                             'code': 'CONFLICT'}, status=status.HTTP_409_CONFLICT)
        return super().destroy(request, *args, **kwargs)


class ZoneViewSet(viewsets.ModelViewSet):
    """Quản lý khu (zone) trong kho. Tạo/sửa: QL kho trở lên."""
    serializer_class = ZoneSerializer
    permission_classes = [WmsControlAccess]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['warehouse']

    def get_queryset(self):
        qs = Zone.objects.select_related('warehouse')
        wh = self.request.query_params.get('warehouse')
        if wh:
            qs = qs.filter(warehouse__code=wh)
        return qs

    def destroy(self, request, *args, **kwargs):
        zone = self.get_object()
        stock = InventoryItem.objects.filter(bin__zone=zone, qty_on_hand__gt=0).count()
        if stock:
            return Response({'detail': f'Khu còn hàng ở {stock} ô — xuất/chuyển hết hàng trước khi xoá.',
                             'code': 'CONFLICT'}, status=status.HTTP_409_CONFLICT)
        try:
            with transaction.atomic():
                InventoryItem.objects.filter(bin__zone=zone).delete()   # ô tồn 0
                zone.bins.all().delete()                                # chặn nếu ô có lịch sử (PROTECT)
                zone.delete()
        except ProtectedError:
            return Response({'detail': 'Khu có ô đã phát sinh giao dịch (lịch sử nhập/xuất) — không xoá được.',
                             'code': 'CONFLICT'}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BinViewSet(viewsets.ModelViewSet):
    """Quản lý ô (bin). Đọc: nội bộ. Tạo/sửa/xoá: QL kho trở lên.
    Lọc ?warehouse=<code>&zone=<code> (theo MÃ) qua get_queryset."""
    serializer_class = BinSerializer
    permission_classes = [WmsControlAccess]

    def get_queryset(self):
        qs = Bin.objects.select_related('zone', 'zone__warehouse')
        wh = self.request.query_params.get('warehouse')
        zone = self.request.query_params.get('zone')
        if wh:
            qs = qs.filter(zone__warehouse__code=wh)
        if zone:
            qs = qs.filter(zone__code=zone)
        return qs

    def perform_create(self, serializer):
        z = serializer.validated_data['zone']
        rack = serializer.validated_data['rack']
        bin_code = serializer.validated_data['bin_code']
        serializer.save(full_code=f"{z.warehouse.code}-{z.code}-{rack}-{bin_code}")

    def destroy(self, request, *args, **kwargs):
        b = self.get_object()
        if b.items.filter(qty_on_hand__gt=0).exists():
            return Response({'detail': 'Ô còn hàng — xuất/chuyển hết trước khi xoá.',
                             'code': 'CONFLICT'}, status=status.HTTP_409_CONFLICT)
        try:
            with transaction.atomic():
                b.items.all().delete()                  # tồn 0
                b.delete()                              # chặn nếu có lịch sử (PROTECT)
        except ProtectedError:
            return Response({'detail': 'Ô đã phát sinh giao dịch — không xoá được.',
                             'code': 'CONFLICT'}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InventoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/wms/inventory/?warehouse=HCM&part=002001&low_stock=true
    + actions adjust/ transfer.
    """
    serializer_class = InventoryItemSerializer
    permission_classes = [WMSPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['part__display_name_vi', 'torch__display_name_vi', 'bin__full_code']

    def get_queryset(self):
        qs = (InventoryItem.objects
              .select_related('bin', 'bin__zone', 'bin__zone__warehouse', 'part', 'torch')
              .annotate(qty_available=F('qty_on_hand') - F('qty_reserved')))
        wh = self.request.query_params.get('warehouse')
        if wh:
            qs = qs.filter(bin__zone__warehouse__code=wh)
        if self.request.query_params.get('part'):
            qs = qs.filter(part=self.request.query_params['part'])
        if self.request.query_params.get('zone'):
            qs = qs.filter(bin__zone__code=self.request.query_params['zone'])
        if self.request.query_params.get('low_stock') == 'true':
            qs = qs.filter(qty_on_hand__lte=F('min_level'))
        return qs

    @action(detail=False, methods=['post'], url_path='adjust')
    def adjust(self, request):
        if not is_wms_control(request.user):
            return Response({'detail': 'Chỉ Quản lý kho trở lên được điều chỉnh tồn.'}, status=403)
        ser = AdjustSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        part  = Part.objects.filter(pk=d.get('part')).first() if d.get('part') else None
        torch = Torch.objects.filter(pk=d.get('torch')).first() if d.get('torch') else None
        if d.get('part') and part is None:
            raise ValidationError({'part': 'Part không tồn tại.'})
        if d.get('torch') and torch is None:
            raise ValidationError({'torch': 'Torch không tồn tại.'})
        prev = InventoryItem.objects.filter(bin=d['bin'], part=part, torch=torch).first()
        prev_qty = prev.qty_on_hand if prev else 0
        item = services.adjust_stock(
            bin_obj=d['bin'], part=part, torch=torch, new_qty=d['new_qty'],
            reason=d['reason'], user=request.user, note=d['note'])
        # Báo quản lý khi điều chỉnh tồn số lượng lớn (giám sát chênh lệch).
        delta = item.qty_on_hand - prev_qty
        if abs(delta) >= ADJUST_NOTIFY_QTY:
            sku = part.pk if part else (torch.pk if torch else '?')
            notify_roles(MANAGER_ROLES, 'stock_adjust',
                         f"Điều chỉnh tồn {sku} tại {d['bin'].full_code}: {delta:+d} "
                         f"(còn {item.qty_on_hand}). {d.get('note') or d['reason']}",
                         link='/wms/movements', exclude_user=request.user)
        return Response(InventoryItemSerializer(item).data)

    @action(detail=False, methods=['post'], url_path='scan-entry')
    def scan_entry(self, request):
        """Quét mã bằng điện thoại để NHẬP DỮ LIỆU tồn kho.

        Body: {code, bin_code, qty, mode, warehouse?}
          - mode='receive' → +qty vào ô (nhập kho nhanh).
          - mode='issue'   → -qty khỏi ô (xuất kho nhanh).
          - mode='count'   → set tồn = qty (kiểm kê).
        code = mã phụ tùng (tokin_part_no); bin_code = full_code của ô.
        """
        code = str(request.data.get('code', '')).strip()
        bin_code = str(request.data.get('bin_code', '')).strip()
        mode = str(request.data.get('mode', 'receive')).strip().lower()
        wh = str(request.data.get('warehouse', '')).strip()
        try:
            qty = int(request.data.get('qty'))
        except (TypeError, ValueError):
            return Response({'detail': 'Số lượng không hợp lệ.'}, status=400)

        if not code or not bin_code:
            return Response({'detail': 'Thiếu mã phụ tùng hoặc mã ô (bin).'}, status=400)
        if mode not in ('receive', 'issue', 'count'):
            return Response({'detail': "mode phải là 'receive', 'issue' hoặc 'count'."}, status=400)
        if mode == 'count' and not is_wms_control(request.user):
            return Response({'detail': 'Kiểm kê đặt lại tồn cần quyền Quản lý kho.'}, status=403)
        if mode in ('receive', 'issue') and qty <= 0:
            return Response({'detail': 'Số lượng phải > 0.'}, status=400)
        if mode == 'count' and qty < 0:
            return Response({'detail': 'Số đếm không được âm.'}, status=400)

        part = Part.objects.filter(pk=code).first()
        torch = None if part else Torch.objects.filter(pk=code).first()
        if part is None and torch is None:
            return Response({'detail': f'Không tìm thấy phụ tùng/súng hàn mã "{code}".'}, status=404)
        bin_qs = Bin.objects.filter(full_code=bin_code)
        if wh:
            bin_qs = bin_qs.filter(zone__warehouse__code=wh)
        bin_obj = bin_qs.first()
        if bin_obj is None:
            return Response({'detail': f'Không tìm thấy ô (bin) mã "{bin_code}".'}, status=404)

        try:
            if mode == 'receive':
                item = services.receive_stock(bin_obj=bin_obj, part=part, torch=torch, qty=qty,
                                              user=request.user, ref_id='scan',
                                              lot_no=str(request.data.get('lot_no', '')).strip(),
                                              lot_expires=request.data.get('lot_expires') or None)
                msg = f'Đã nhập +{qty} vào {bin_obj.full_code}.'
            elif mode == 'issue':
                item = services.issue_stock(bin_obj=bin_obj, part=part, torch=torch, qty=qty,
                                            user=request.user, ref_id='scan')
                msg = f'Đã xuất -{qty} khỏi {bin_obj.full_code}.'
            else:
                item = services.adjust_stock(bin_obj=bin_obj, part=part, torch=torch, new_qty=qty,
                                             reason='adjust', user=request.user,
                                             note='Kiểm kê (quét)')
                msg = f'Đã cập nhật tồn = {qty} tại {bin_obj.full_code}.'
        except (services.InsufficientStock, services.CountLockError) as e:
            return Response({'detail': str(e), 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)

        obj = part or torch
        return Response({
            'detail': msg, 'mode': mode,
            'part_no': obj.pk, 'part_name': obj.display_name_vi,
            'bin_code': bin_obj.full_code, 'qty_on_hand': item.qty_on_hand,
            'item': InventoryItemSerializer(item).data,
        })

    @action(detail=False, methods=['post'], url_path='transfer')
    def transfer(self, request):
        ser = TransferSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        part  = Part.objects.filter(pk=d.get('part')).first() if d.get('part') else None
        torch = Torch.objects.filter(pk=d.get('torch')).first() if d.get('torch') else None
        try:
            services.transfer_stock(from_bin=d['from_bin'], to_bin=d['to_bin'],
                                    part=part, torch=torch, qty=d['qty'], user=request.user)
        except services.InsufficientStock as e:
            return Response({'detail': str(e), 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        return Response({'detail': 'Đã chuyển kho.'}, status=status.HTTP_200_OK)


class SerialNumberViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SerialNumberSerializer
    permission_classes = [WMSPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['status', 'torch']
    search_fields = ['serial']

    def get_queryset(self):
        return SerialNumber.objects.select_related('torch', 'bin', 'sold_to_customer')

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """Lịch sử 1 serial (2 chiều): bán cho ai, đơn nào, bảo hành, + ticket liên quan."""
        from datetime import date

        from apps.crm.models import Ticket
        s = self.get_object()
        tickets = (Ticket.objects.filter(serial_no=s.serial)
                   .values('code', 'title', 'status', 'created_at').order_by('-created_at'))
        wu = s.warranty_until
        warranty = ('none' if not wu else 'valid' if wu >= date.today() else 'expired')
        return Response({
            'serial': s.serial,
            'torch': str(s.torch_id),
            'status': s.status,
            'sold_to_customer': s.sold_to_customer.name if s.sold_to_customer_id else None,
            'sold_to_customer_id': str(s.sold_to_customer_id) if s.sold_to_customer_id else None,
            'sold_order': s.sold_order or None,
            'received_at': s.received_at.isoformat() if s.received_at else None,
            'warranty_until': wu.isoformat() if wu else None,
            'warranty_state': warranty,
            'tickets': list(tickets),
        })


class LotViewSet(viewsets.ReadOnlyModelViewSet):
    """Lô hàng (FEFO). ?expiring_days=N → lô còn hàng sắp hết hạn trong N ngày;
    ?warehouse=HCM lọc theo kho."""
    serializer_class = LotSerializer
    permission_classes = [WMSPermission]

    def get_queryset(self):
        qs = Lot.objects.select_related('part', 'bin').filter(qty_remaining__gt=0)
        wh = self.request.query_params.get('warehouse')
        if wh:
            qs = qs.filter(bin__zone__warehouse__code=wh)
        days = self.request.query_params.get('expiring_days')
        if days:
            from datetime import date, timedelta
            cutoff = date.today() + timedelta(days=int(days))
            qs = qs.filter(expires_at__isnull=False, expires_at__lte=cutoff)
        return qs.order_by('expires_at')


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StockMovementSerializer
    permission_classes = [WMSPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['reason', 'warehouse', 'part', 'bin']

    def get_queryset(self):
        return StockMovement.objects.select_related('by_user').order_by('-ts')


class ASNViewSet(viewsets.ModelViewSet):
    serializer_class = ASNSerializer
    permission_classes = [WMSPermission]
    queryset = ASN.objects.all()

    @action(detail=True, methods=['post'], url_path='arrive')
    def arrive(self, request, pk=None):
        asn = self.get_object()
        if asn.is_arrived:
            return Response({'detail': 'ASN đã đánh dấu về.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        inbound = InboundOrder.objects.create(
            code=f"IN-{asn.code.split('-', 1)[-1]}", warehouse=asn.warehouse, asn=asn,
            created_by=request.user, updated_by=request.user)
        asn.is_arrived = True
        asn.save(update_fields=['is_arrived'])
        _publish('StockReceived', {'asn': asn.code, 'inbound': inbound.code,
                                   'warehouse': asn.warehouse.code})
        notify_roles(WAREHOUSE_STAFF, 'inbound_created',
                     f"Phiếu nhập {inbound.code} cần nhận hàng (kho {asn.warehouse.code}).",
                     link='/wms/inbound')
        return Response(InboundOrderSerializer(inbound).data, status=status.HTTP_201_CREATED)


class InboundViewSet(viewsets.ModelViewSet):
    serializer_class = InboundOrderSerializer
    permission_classes = [WMSPermission]
    queryset = InboundOrder.objects.prefetch_related('lines')

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_create(self, serializer):
        inbound = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        # Báo nhân viên kho: có phiếu nhập mới cần nhận hàng (trừ người tự tạo).
        notify_roles(WAREHOUSE_STAFF, 'inbound_created',
                     f"Phiếu nhập {inbound.code} cần nhận hàng (kho {inbound.warehouse.code}).",
                     link='/wms/inbound', exclude_user=self.request.user)

    @action(detail=True, methods=['get'], url_path='export-xlsx')
    def export_xlsx(self, request, pk=None):
        """Xuất phiếu nhập kho ra Excel (đầu trang NCC nếu có + bảng dòng hàng)."""
        from apps.common.excel import make_document_xlsx, supplier_party, xlsx_response
        o = self.get_object()
        rows = []
        for l in o.lines.all():
            item = l.part or l.torch
            rows.append((str(item.pk) if item else '—',
                         getattr(item, 'display_name_vi', '') if item else '',
                         l.qty_expected, l.qty_received))
        sup = getattr(o.asn, 'supplier', None) if o.asn_id else None
        party = supplier_party(sup) if sup is not None and hasattr(sup, 'name') else None
        data = make_document_xlsx(
            sheet_title='PhieuNhap', doc_title='PHIẾU NHẬP KHO', doc_code=o.code,
            doc_date=o.created_at.strftime('%d/%m/%Y'),
            party=party, party_label='NHÀ CUNG CẤP:',
            meta=[('Kho nhập:', o.warehouse.code), ('Trạng thái:', o.get_status_display())],
            columns=[('Mã', 16, 'text'), ('Tên hàng', 40, 'text'),
                     ('SL dự kiến', 12, 'int'), ('Thực nhận', 12, 'int')],
            rows=rows,
            signatures=['NGƯỜI GIAO', 'THỦ KHO', 'KẾ TOÁN'])
        return xlsx_response(data, f'phieu_nhap_{o.code}.xlsx')

    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm(self, request, pk=None):
        """Nhận hàng thực: chỉ cộng tồn phần MỚI nhận (delta = received - putaway).
        Hỗ trợ NHẬN MỘT PHẦN: body {partial:true} → không tự coi là nhận đủ;
        giao thiếu → phiếu giữ trạng thái `partial` (còn mở), confirm tiếp được."""
        inbound = self.get_object()
        if inbound.status not in ('draft', 'confirmed', 'partial'):
            return Response({'detail': 'Trạng thái không cho xác nhận.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        partial_flag = bool(request.data.get('partial'))
        shortage_note = str(request.data.get('shortage_note', '')).strip()
        fully = True
        for line in inbound.lines.all():
            received = line.qty_received
            # Không quét + không phải nhận-một-phần → coi như giao đủ.
            if received == 0 and not partial_flag:
                received = line.qty_expected
            delta = received - line.qty_putaway
            if line.target_bin_id and delta > 0:
                services.receive_stock(
                    bin_obj=line.target_bin, part=line.part, torch=line.torch,
                    qty=delta, user=request.user, ref_id=inbound.code,
                    lot_no=line.lot_no, lot_expires=line.lot_expires)
                # Giá vốn WAC từ đơn giá nhập (cho hàng nhập tay, không qua PO).
                if line.part_id and line.unit_cost:
                    from apps.catalog.costing import update_wac
                    update_wac(line.part, delta, line.unit_cost)
                line.qty_received = received
                line.qty_putaway = received
                line.save(update_fields=['qty_received', 'qty_putaway'])
            # Súng hàn: tạo serial từng cây (bảo hành) — bỏ qua serial đã tồn tại (idempotent).
            if line.torch_id and line.serials_raw:
                from .models import SerialNumber
                for s in line.serials_raw.splitlines():
                    s = s.strip()
                    if s and not SerialNumber.objects.filter(serial=s).exists():
                        SerialNumber.objects.create(serial=s, torch=line.torch,
                                                    bin=line.target_bin, status='in_stock')
            if line.qty_putaway < line.qty_expected:
                fully = False
        inbound.status = 'putaway' if fully else 'partial'
        if fully:
            inbound.received_at = timezone.now()
        if shortage_note:
            inbound.shortage_note = shortage_note
        inbound.save(update_fields=['status', 'received_at', 'shortage_note'])
        # Sync ngược về Đơn mua (nếu phiếu tạo từ PO): cập nhật SL đã nhận + trạng thái PO.
        if inbound.purchase_order_id:
            self._sync_purchase_order(inbound)
        _publish('StockReceived', {'inbound': inbound.code, 'warehouse': inbound.warehouse.code,
                                   'partial': not fully})
        return Response(InboundOrderSerializer(inbound).data)

    @staticmethod
    def _sync_purchase_order(inbound) -> None:
        """Cập nhật qty_received + trạng thái PO theo SL đã cất của phiếu nhập (1 dòng/part)."""
        po = inbound.purchase_order
        if po is None:
            return
        for il in inbound.lines.all():
            if not il.part_id:
                continue
            pol = po.lines.filter(part=il.part).first()
            if pol:
                # qty_expected phiếu = SL CÒN LẠI lúc tạo → received = qty − còn_lại + đã_cất.
                pol.qty_received = min(pol.qty, pol.qty - il.qty_expected + il.qty_putaway)
                pol.save(update_fields=['qty_received'])
        done = all(l.qty_received >= l.qty for l in po.lines.all())
        from apps.purchasing.models import PurchaseStatus
        po.status = PurchaseStatus.RECEIVED if done else PurchaseStatus.PARTIAL
        if done:
            po.received_at = timezone.now()
        po.save(update_fields=['status', 'received_at'])

    @action(detail=True, methods=['post'], url_path='scan-receive')
    def scan_receive(self, request, pk=None):
        """Quét nhận hàng theo phiếu: cộng dồn qty_received cho dòng khớp mã."""
        inbound = self.get_object()
        if inbound.status not in ('draft', 'confirmed', 'partial'):
            return Response({'detail': 'Phiếu đã xử lý.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        code = str(request.data.get('code', '')).strip()
        try:
            qty = int(request.data.get('qty', 1))
        except (TypeError, ValueError):
            return Response({'detail': 'Số lượng không hợp lệ.'}, status=400)
        if not code or qty <= 0:
            return Response({'detail': 'Thiếu mã hoặc số lượng.'}, status=400)
        line = next((l for l in inbound.lines.all()
                     if (l.part_id == code or l.torch_id == code)), None)
        if line is None:
            return Response({'detail': f'Mã "{code}" không có trong phiếu nhập này.'}, status=404)
        line.qty_received = min(line.qty_received + qty, line.qty_expected)
        line.save(update_fields=['qty_received'])
        done = all(l.qty_received >= l.qty_expected for l in inbound.lines.all())
        if inbound.status == 'draft':
            inbound.status = 'confirmed'; inbound.save(update_fields=['status'])
        return Response({
            'detail': f'Đã nhận {line.qty_received}/{line.qty_expected} mã {code}.',
            'code': code, 'received': line.qty_received, 'expected': line.qty_expected,
            'all_done': done,
        })


class CycleCountLineSerializer(serializers.ModelSerializer):
    part_name = serializers.SerializerMethodField()
    bin_code  = serializers.CharField(source='bin.full_code', read_only=True)
    diff      = serializers.IntegerField(read_only=True)

    class Meta:
        model = CycleCountLine
        fields = ['id', 'bin', 'bin_code', 'part', 'torch', 'part_name',
                  'system_qty', 'counted_qty', 'diff', 'counted_at']
        read_only_fields = fields

    def get_part_name(self, obj):
        o = obj.part or obj.torch
        return getattr(o, 'display_name_vi', None)


class CycleCountSerializer(serializers.ModelSerializer):
    lines = CycleCountLineSerializer(many=True, read_only=True)
    warehouse_code = serializers.CharField(source='warehouse.code', read_only=True)

    class Meta:
        model = CycleCount
        fields = ['id', 'code', 'warehouse', 'warehouse_code', 'status', 'note',
                  'applied_at', 'created_at', 'lines']
        read_only_fields = ['id', 'code', 'status', 'applied_at', 'created_at', 'lines']


class CycleCountViewSet(viewsets.ModelViewSet):
    """Phiên kiểm kê: tạo → quét đếm (scan) → áp dụng (apply) điều chỉnh tồn."""
    serializer_class = CycleCountSerializer
    permission_classes = [WMSPermission]
    queryset = CycleCount.objects.select_related('warehouse').prefetch_related('lines')

    def perform_create(self, serializer):
        from django.utils import timezone
        wh = serializer.validated_data['warehouse']
        year = timezone.now().year
        pre = f'KK-{year}-'
        last = CycleCount.objects.filter(code__startswith=pre).order_by('-code').first()
        seq = (int(last.code.rsplit('-', 1)[-1]) + 1) if last else 1
        serializer.save(code=f'{pre}{seq:03d}', created_by=self.request.user,
                        updated_by=self.request.user)

    @action(detail=True, methods=['post'])
    def scan(self, request, pk=None):
        """Quét đếm 1 mặt hàng tại 1 ô: lưu tồn hệ thống + số đếm thực tế."""
        cc = self.get_object()
        if cc.status != 'open':
            return Response({'detail': 'Phiên đã đóng.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        code = str(request.data.get('code', '')).strip()
        bin_code = str(request.data.get('bin_code', '')).strip()
        try:
            counted = int(request.data.get('counted_qty'))
        except (TypeError, ValueError):
            return Response({'detail': 'Số đếm không hợp lệ.'}, status=400)
        if not code or not bin_code or counted < 0:
            return Response({'detail': 'Thiếu mã hàng, mã ô hoặc số đếm.'}, status=400)
        part = Part.objects.filter(pk=code).first()
        torch = None if part else Torch.objects.filter(pk=code).first()
        if part is None and torch is None:
            return Response({'detail': f'Không tìm thấy mã "{code}".'}, status=404)
        bin_obj = Bin.objects.filter(full_code=bin_code, zone__warehouse=cc.warehouse).first()
        if bin_obj is None:
            return Response({'detail': f'Không có ô "{bin_code}" trong kho {cc.warehouse.code}.'},
                            status=404)
        inv = InventoryItem.objects.filter(bin=bin_obj, part=part, torch=torch).first()
        system_qty = inv.qty_on_hand if inv else 0
        line, _ = CycleCountLine.objects.update_or_create(
            session=cc, bin=bin_obj, part=part, torch=torch,
            defaults={'system_qty': system_qty, 'counted_qty': counted})
        return Response(CycleCountLineSerializer(line).data)

    @action(detail=True, methods=['post'])
    def apply(self, request, pk=None):
        """Áp dụng kiểm kê: set tồn từng dòng = số đếm (ghi movement chênh lệch).
        Duyệt chênh lệch = quyền Quản lý kho trở lên."""
        from django.utils import timezone
        if not is_wms_control(request.user):
            return Response({'detail': 'Duyệt kiểm kê cần quyền Quản lý kho.'}, status=403)
        cc = self.get_object()
        if cc.status != 'open':
            return Response({'detail': 'Phiên đã đóng.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        applied, total_diff, diff_lines = 0, 0, 0
        for line in cc.lines.all():
            services.adjust_stock(bin_obj=line.bin, part=line.part, torch=line.torch,
                                  new_qty=line.counted_qty, reason='adjust',
                                  user=request.user, note=f'Kiểm kê {cc.code}')
            total_diff += line.diff
            if line.diff:
                diff_lines += 1
            applied += 1
        cc.status = 'applied'; cc.applied_at = timezone.now()
        cc.save(update_fields=['status', 'applied_at'])
        # Báo quản lý khi kiểm kê có chênh lệch tồn (rủi ro mất/thừa hàng).
        if diff_lines:
            notify_roles(MANAGER_ROLES, 'cyclecount_variance',
                         f"Kiểm kê {cc.code} (kho {cc.warehouse.code}): {diff_lines} dòng lệch, "
                         f"chênh lệch ròng {total_diff:+d} — cần kiểm tra.",
                         link='/wms/cycle-count', exclude_user=request.user)
        return Response({'detail': f'Đã áp dụng {applied} dòng kiểm kê.',
                         'applied': applied, 'total_diff': total_diff})


class OutboundViewSet(viewsets.ModelViewSet):
    serializer_class = OutboundOrderSerializer
    permission_classes = [WMSPermission]
    queryset = OutboundOrder.objects.prefetch_related('lines')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    @action(detail=True, methods=['get'], url_path='export-xlsx')
    def export_xlsx(self, request, pk=None):
        """Xuất phiếu xuất kho ra Excel (đầu trang thông tin KH + bảng dòng hàng)."""
        from apps.common.excel import customer_party, make_document_xlsx, xlsx_response
        o = self.get_object()
        rows = []
        for l in o.lines.all():
            item = l.part or l.torch
            rows.append((str(item.pk) if item else '—',
                         getattr(item, 'display_name_vi', '') if item else '',
                         l.qty_ordered, l.qty_picked))
        party = customer_party(o.customer) if o.customer_id else None
        data = make_document_xlsx(
            sheet_title='PhieuXuat', doc_title='PHIẾU XUẤT KHO', doc_code=o.code,
            doc_date=o.created_at.strftime('%d/%m/%Y'),
            party_label='NGƯỜI NHẬN / KHÁCH HÀNG:', party=party,
            meta=[('Kho xuất:', o.warehouse.code), ('Đơn bán:', o.sales_order_code or '—'),
                  ('Trạng thái:', o.get_status_display())],
            columns=[('Mã', 16, 'text'), ('Tên hàng', 40, 'text'),
                     ('SL đặt', 12, 'int'), ('Thực soạn', 12, 'int')],
            rows=rows,
            signatures=['THỦ KHO', 'NGƯỜI VẬN CHUYỂN', 'NGƯỜI NHẬN'])
        return xlsx_response(data, f'phieu_xuat_{o.code}.xlsx')

    @action(detail=True, methods=['get'], url_path='pick-list')
    def pick_list(self, request, pk=None):
        outbound = self.get_object()
        try:
            picks = services.generate_pick_list(outbound)
        except services.InsufficientStock as e:
            return Response({'detail': str(e), 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        return Response(PickListItemSerializer(picks, many=True).data)

    @action(detail=True, methods=['post'], url_path='ship')
    def ship(self, request, pk=None):
        outbound = self.get_object()
        if outbound.status not in ('picking', 'picked', 'partial'):
            return Response({'detail': 'Cần soạn hàng trước khi giao.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        try:
            services.confirm_pick_and_ship(outbound, user=request.user)
        except services.CountLockError as e:
            return Response({'detail': str(e), 'code': 'CONFLICT'}, status=409)
        except ValueError as e:
            return Response({'detail': str(e), 'code': 'VALIDATION_FAILED'}, status=400)
        _publish('OrderShipped', {'outbound': outbound.code,
                                  'warehouse': outbound.warehouse.code})
        return Response(OutboundOrderSerializer(outbound).data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """Kho TỪ CHỐI phiếu xuất (hết hàng/hàng lỗi): hủy phiếu, nhả tồn đã giữ,
        đưa đơn bán về `active` + báo 🔔 cho sale xử lý với khách."""
        from django.db.models import F as _F

        from apps.common.models import notify
        outbound = self.get_object()
        if outbound.status in ('shipped', 'cancelled'):
            return Response({'detail': 'Phiếu đã giao/hủy, không từ chối được.',
                             'code': 'CONFLICT'}, status=status.HTTP_409_CONFLICT)
        reason = str(request.data.get('reason', '')).strip() or 'không nêu lý do'
        # Nhả phần tồn đang giữ (reserved) của các pick chưa giao.
        for line in outbound.lines.all():
            for pick in line.picks.filter(is_picked=False):
                InventoryItem.objects.filter(
                    bin=pick.bin, part=line.part, torch=line.torch).update(
                    qty_reserved=_F('qty_reserved') - pick.qty)
        outbound.status = 'cancelled'
        outbound.save(update_fields=['status'])
        # Sync ngược CRM: đưa đơn về active để sale xử lý lại.
        if outbound.sales_order_code:
            from apps.sales.models import SalesOrder
            order = SalesOrder.objects.filter(code=outbound.sales_order_code,
                                              status='shipping').first()
            if order:
                order.status = 'active'
                order.save(update_fields=['status'])
                if order.owner_id:
                    notify(order.owner, 'outbound_rejected',
                           f'Kho TỪ CHỐI giao đơn {order.code} (lý do: {reason}). '
                           'Vui lòng xử lý với khách.', link='/orders')
        return Response(OutboundOrderSerializer(outbound).data)

    @action(detail=True, methods=['post'], url_path='scan-pick')
    def scan_pick(self, request, pk=None):
        """Quét soạn hàng theo phiếu: trừ tồn khỏi ô + cộng dồn qty_picked dòng khớp."""
        outbound = self.get_object()
        if outbound.status in ('shipped', 'cancelled'):
            return Response({'detail': 'Phiếu đã xử lý.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        code = str(request.data.get('code', '')).strip()
        bin_code = str(request.data.get('bin_code', '')).strip()
        try:
            qty = int(request.data.get('qty', 1))
        except (TypeError, ValueError):
            return Response({'detail': 'Số lượng không hợp lệ.'}, status=400)
        if not code or not bin_code or qty <= 0:
            return Response({'detail': 'Thiếu mã hàng, mã ô hoặc số lượng.'}, status=400)
        line = next((l for l in outbound.lines.all()
                     if (l.part_id == code or l.torch_id == code)), None)
        if line is None:
            return Response({'detail': f'Mã "{code}" không có trong phiếu xuất này.'}, status=404)
        remaining = line.qty_ordered - line.qty_picked
        if qty > remaining:
            return Response({'detail': f'Chỉ còn cần soạn {remaining} cho mã {code}.'}, status=400)
        # FEFO: cảnh báo nếu quét lô KHÔNG phải lô ưu tiên (hết hạn sớm nhất).
        lot_no = str(request.data.get('lot_no', '')).strip()
        confirm_lot = bool(request.data.get('confirm_lot'))
        if line.part_id and lot_no and not confirm_lot:
            priority = (Lot.objects.filter(part_id=line.part_id, qty_remaining__gt=0,
                                           expires_at__isnull=False)
                        .order_by('expires_at').first())
            if priority and priority.lot_no != lot_no:
                return Response({
                    'detail': f'Lô "{lot_no}" KHÔNG phải lô ưu tiên FEFO. Nên lấy lô '
                              f'"{priority.lot_no}" (hết hạn {priority.expires_at}). '
                              'Xác nhận lại nếu chắc chắn.',
                    'code': 'WRONG_LOT', 'priority_lot': priority.lot_no,
                    'priority_expires': priority.expires_at.isoformat(),
                }, status=status.HTTP_409_CONFLICT)
        bin_obj = Bin.objects.filter(full_code=bin_code,
                                     zone__warehouse=outbound.warehouse).first()
        if bin_obj is None:
            return Response({'detail': f'Không có ô "{bin_code}" trong kho {outbound.warehouse.code}.'},
                            status=404)
        try:
            services.issue_stock(bin_obj=bin_obj, part=line.part, torch=line.torch,
                                 qty=qty, user=request.user, ref_id=outbound.code)
        except (services.InsufficientStock, services.CountLockError) as e:
            return Response({'detail': str(e), 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        line.qty_picked += qty
        line.save(update_fields=['qty_picked'])
        done = all(l.qty_picked >= l.qty_ordered for l in outbound.lines.all())
        outbound.status = 'picked' if done else 'picking'
        outbound.save(update_fields=['status'])
        return Response({
            'detail': f'Đã soạn {line.qty_picked}/{line.qty_ordered} mã {code} từ {bin_code}.',
            'code': code, 'picked': line.qty_picked, 'ordered': line.qty_ordered,
            'all_done': done,
        })


class OpsKpiView(APIView):
    """KPI vận hành kho (Quản lý kho trở lên): năng suất nhập/xuất, chênh lệch
    kiểm kê, tồn theo zone, hiệu suất nhân sự. GET ?warehouse=HCM&days=30."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import date, timedelta

        from .models import CycleCount, CycleCountLine, InventoryItem, StockMovement
        if not is_wms_control(request.user):
            return Response({'detail': 'Cần quyền Quản lý kho trở lên.'}, status=403)
        wh = request.query_params.get('warehouse')
        try:
            days = max(1, int(request.query_params.get('days', 30)))
        except ValueError:
            days = 30
        cutoff = date.today() - timedelta(days=days)

        mv = StockMovement.objects.filter(ts__date__gte=cutoff)
        if wh:
            mv = mv.filter(warehouse__code=wh)

        def agg(reason):
            a = mv.filter(reason=reason).aggregate(c=Count('id'), q=Sum('delta'))
            return a['c'] or 0, int(a['q'] or 0)
        in_c, in_q = agg('inbound')
        out_c, out_q = agg('outbound')
        adj_c, _ = agg('adjust')
        trf_c, _ = agg('transfer')

        # Hiệu suất nhân sự: số thao tác theo người (top 8)
        by_user = list(mv.exclude(by_user__isnull=True)
                       .values('by_user__username')
                       .annotate(ops=Count('id')).order_by('-ops')[:8])

        # Chênh lệch kiểm kê: phiên đã áp dụng trong kỳ
        sessions = CycleCount.objects.filter(status='applied', applied_at__date__gte=cutoff)
        if wh:
            sessions = sessions.filter(warehouse__code=wh)
        cc_lines = CycleCountLine.objects.filter(session__in=sessions)
        abs_diff = cc_lines.annotate(ad=Abs(F('counted_qty') - F('system_qty'))) \
            .aggregate(s=Sum('ad'))['s'] or 0
        counted_lines = cc_lines.count()
        mismatch = cc_lines.exclude(counted_qty=F('system_qty')).count()
        accuracy = round((1 - mismatch / counted_lines) * 100, 1) if counted_lines else 100.0

        # Tồn theo zone
        inv = InventoryItem.objects.all()
        if wh:
            inv = inv.filter(bin__zone__warehouse__code=wh)
        by_zone = list(inv.values('bin__zone__code', 'bin__zone__name')
                       .annotate(sku=Count('id'), qty=Sum('qty_on_hand'))
                       .order_by('bin__zone__code'))
        low_stock = inv.filter(qty_on_hand__lte=F('min_level')).count()

        # Vòng quay hàng hóa (xấp xỉ): tổng SL xuất trong kỳ / tồn hiện tại,
        # quy về năm. turnover_year = (out_qty/tồn) × (365/days).
        on_hand = int(inv.aggregate(s=Sum('qty_on_hand'))['s'] or 0)
        out_qty = abs(out_q)
        turnover = round((out_qty / on_hand) * (365 / days), 2) if on_hand else 0.0

        return Response({
            'warehouse': wh or 'ALL', 'days': days,
            'inbound':  {'ops': in_c, 'qty': in_q},
            'outbound': {'ops': out_c, 'qty': abs(out_q)},
            'inventory_turnover': turnover, 'on_hand_total': on_hand,
            'adjust_ops': adj_c, 'transfer_ops': trf_c,
            'cycle_count': {'sessions': sessions.count(), 'lines': counted_lines,
                            'mismatch': mismatch, 'abs_diff': int(abs_diff),
                            'accuracy_pct': accuracy},
            'by_user': [{'user': u['by_user__username'], 'ops': u['ops']} for u in by_user],
            'by_zone': [{'zone': z['bin__zone__code'], 'name': z['bin__zone__name'],
                         'sku': z['sku'], 'qty': int(z['qty'] or 0)} for z in by_zone],
            'low_stock': low_stock,
        })
