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

from django.db.models import F
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.catalog.models import Part, Torch

from . import services
from .models import (
    ASN, Bin, InboundOrder, InventoryItem, Lot, OutboundOrder,
    SerialNumber, StockMovement, Warehouse, Zone,
)
from .permissions import WMSPermission
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


class WarehouseViewSet(viewsets.ReadOnlyModelViewSet):
    """FE đọc để quyết hiện/ẩn switcher (B.4): ẩn khi count==1."""
    queryset = Warehouse.objects.filter(is_active=True)
    serializer_class = WarehouseSerializer
    permission_classes = [WMSPermission]


class ZoneViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ZoneSerializer
    permission_classes = [WMSPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['warehouse']

    def get_queryset(self):
        qs = Zone.objects.select_related('warehouse')
        wh = self.request.query_params.get('warehouse')
        if wh:
            qs = qs.filter(warehouse__code=wh)
        return qs


class BinViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BinSerializer
    permission_classes = [WMSPermission]

    def get_queryset(self):
        qs = Bin.objects.select_related('zone', 'zone__warehouse')
        wh = self.request.query_params.get('warehouse')
        zone = self.request.query_params.get('zone')
        if wh:
            qs = qs.filter(zone__warehouse__code=wh)
        if zone:
            qs = qs.filter(zone__code=zone)
        return qs


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
        ser = AdjustSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        part  = Part.objects.filter(pk=d.get('part')).first() if d.get('part') else None
        torch = Torch.objects.filter(pk=d.get('torch')).first() if d.get('torch') else None
        if d.get('part') and part is None:
            raise ValidationError({'part': 'Part không tồn tại.'})
        if d.get('torch') and torch is None:
            raise ValidationError({'torch': 'Torch không tồn tại.'})
        item = services.adjust_stock(
            bin_obj=d['bin'], part=part, torch=torch, new_qty=d['new_qty'],
            reason=d['reason'], user=request.user, note=d['note'])
        return Response(InventoryItemSerializer(item).data)

    @action(detail=False, methods=['post'], url_path='scan-entry')
    def scan_entry(self, request):
        """Quét mã bằng điện thoại để NHẬP DỮ LIỆU tồn kho.

        Body: {code, bin_code, qty, mode, warehouse?}
          - mode='receive' → +qty vào ô (nhập kho nhanh).
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
        if mode not in ('receive', 'count'):
            return Response({'detail': "mode phải là 'receive' hoặc 'count'."}, status=400)
        if mode == 'receive' and qty <= 0:
            return Response({'detail': 'Số lượng nhập phải > 0.'}, status=400)
        if mode == 'count' and qty < 0:
            return Response({'detail': 'Số đếm không được âm.'}, status=400)

        part = Part.objects.filter(pk=code).first()
        if part is None:
            return Response({'detail': f'Không tìm thấy phụ tùng mã "{code}".'}, status=404)
        bin_qs = Bin.objects.filter(full_code=bin_code)
        if wh:
            bin_qs = bin_qs.filter(zone__warehouse__code=wh)
        bin_obj = bin_qs.first()
        if bin_obj is None:
            return Response({'detail': f'Không tìm thấy ô (bin) mã "{bin_code}".'}, status=404)

        if mode == 'receive':
            item = services.receive_stock(bin_obj=bin_obj, part=part, qty=qty,
                                          user=request.user, ref_id='scan')
            msg = f'Đã nhập +{qty} vào {bin_obj.full_code}.'
        else:
            item = services.adjust_stock(bin_obj=bin_obj, part=part, new_qty=qty,
                                         reason='adjust', user=request.user,
                                         note='Kiểm kê (quét)')
            msg = f'Đã cập nhật tồn = {qty} tại {bin_obj.full_code}.'

        return Response({
            'detail': msg, 'mode': mode,
            'part_no': part.tokin_part_no, 'part_name': part.display_name_vi,
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
        return SerialNumber.objects.select_related('torch', 'bin')


class LotViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LotSerializer
    permission_classes = [WMSPermission]
    queryset = Lot.objects.select_related('part', 'bin').order_by('expires_at')


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
        return Response(InboundOrderSerializer(inbound).data, status=status.HTTP_201_CREATED)


class InboundViewSet(viewsets.ModelViewSet):
    serializer_class = InboundOrderSerializer
    permission_classes = [WMSPermission]
    queryset = InboundOrder.objects.prefetch_related('lines')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm(self, request, pk=None):
        """Nhận hàng thực: +tồn cho từng line theo target_bin, ghi movement."""
        inbound = self.get_object()
        if inbound.status not in ('draft', 'confirmed'):
            return Response({'detail': 'Trạng thái không cho xác nhận.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        for line in inbound.lines.all():
            if not line.target_bin_id or line.qty_expected <= 0:
                continue
            services.receive_stock(
                bin_obj=line.target_bin, part=line.part, torch=line.torch,
                qty=line.qty_expected, user=request.user, ref_id=inbound.code,
                lot_no=line.lot_no)
            line.qty_received = line.qty_expected
            line.save(update_fields=['qty_received'])
        inbound.status = 'putaway'
        inbound.received_at = timezone.now()
        inbound.save(update_fields=['status', 'received_at'])
        _publish('StockReceived', {'inbound': inbound.code, 'warehouse': inbound.warehouse.code})
        return Response(InboundOrderSerializer(inbound).data)


class OutboundViewSet(viewsets.ModelViewSet):
    serializer_class = OutboundOrderSerializer
    permission_classes = [WMSPermission]
    queryset = OutboundOrder.objects.prefetch_related('lines')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

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
        if outbound.status not in ('picking', 'picked'):
            return Response({'detail': 'Cần soạn hàng trước khi giao.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        services.confirm_pick_and_ship(outbound, user=request.user)
        _publish('OrderShipped', {'outbound': outbound.code,
                                  'warehouse': outbound.warehouse.code})
        return Response(OutboundOrderSerializer(outbound).data)
