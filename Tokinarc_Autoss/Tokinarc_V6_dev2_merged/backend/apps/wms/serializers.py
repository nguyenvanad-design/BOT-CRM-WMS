"""
Tokinarc V6.C — apps/wms/serializers.py

Theo pattern apps/crm: list serializer gọn, detail serializer đầy đủ,
validate_*() cho business rule. Action serializers cho adjust/transfer/pick.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import (
    ASN, Bin, InboundLine, InboundOrder, InventoryItem, Lot,
    OutboundLine, OutboundOrder, PickListItem, SerialNumber, StockMovement,
    Warehouse, Zone,
)


# ─── Cấu trúc kho ────────────────────────────────────────────────────────────
class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Warehouse
        fields = ['id', 'code', 'name', 'address', 'is_active', 'is_default',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class ZoneSerializer(serializers.ModelSerializer):
    warehouse_code = serializers.CharField(source='warehouse.code', read_only=True)
    bin_count      = serializers.SerializerMethodField()

    class Meta:
        model  = Zone
        fields = ['id', 'warehouse', 'warehouse_code', 'code', 'name', 'purpose', 'bin_count']

    def get_bin_count(self, obj) -> int:
        return obj.bins.count()


class BinSerializer(serializers.ModelSerializer):
    warehouse_code = serializers.CharField(source='zone.warehouse.code', read_only=True)
    zone_code      = serializers.CharField(source='zone.code', read_only=True)
    zone_name      = serializers.CharField(source='zone.name', read_only=True)

    class Meta:
        model  = Bin
        fields = ['id', 'zone', 'zone_code', 'zone_name', 'warehouse_code', 'rack',
                  'bin_code', 'full_code', 'capacity']
        read_only_fields = ['full_code']


# ─── Tồn kho ─────────────────────────────────────────────────────────────────
class InventoryItemSerializer(serializers.ModelSerializer):
    bin_code       = serializers.CharField(source='bin.full_code', read_only=True)
    warehouse_code = serializers.CharField(source='bin.zone.warehouse.code', read_only=True)
    qty_available  = serializers.IntegerField(read_only=True)
    item_name      = serializers.SerializerMethodField()
    category       = serializers.SerializerMethodField()

    class Meta:
        model  = InventoryItem
        fields = ['id', 'bin', 'bin_code', 'warehouse_code', 'part', 'torch',
                  'item_name', 'category', 'qty_on_hand', 'qty_reserved', 'qty_available',
                  'min_level', 'updated_at']
        read_only_fields = ['id', 'updated_at']

    def get_item_name(self, obj) -> str:
        if obj.part_id:
            return f"{obj.part_id} — {getattr(obj.part, 'display_name_vi', '')}"
        return f"{obj.torch_id} — {getattr(obj.torch, 'display_name_vi', '')}"

    def get_category(self, obj) -> str:
        # Loại sản phẩm (đặt tên kệ): category cho phụ tùng, family cho súng hàn.
        if obj.part_id:
            return getattr(obj.part, 'category', '') or ''
        return getattr(obj.torch, 'family', '') or ''

    def validate(self, attrs):
        if bool(attrs.get('part')) == bool(attrs.get('torch')):
            raise serializers.ValidationError("Phải có đúng một trong part hoặc torch.")
        return attrs


class SerialNumberSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SerialNumber
        fields = ['id', 'serial', 'torch', 'bin', 'status', 'sold_to_customer',
                  'sold_order', 'received_at', 'warranty_until',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class LotSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Lot
        fields = ['id', 'lot_no', 'part', 'qty_remaining', 'received_date',
                  'expires_at', 'bin']


class StockMovementSerializer(serializers.ModelSerializer):
    by_username = serializers.CharField(source='by_user.username', read_only=True)

    class Meta:
        model  = StockMovement
        fields = ['id', 'ts', 'warehouse', 'part', 'torch', 'bin', 'delta',
                  'reason', 'ref_kind', 'ref_id', 'by_username', 'note']


# ─── Inbound / Outbound (nested lines) ───────────────────────────────────────
def _line_item_name(obj):
    """Tên hiển thị của mặt hàng (part hoặc torch) cho 1 dòng phiếu kho."""
    o = obj.part or obj.torch
    return (getattr(o, 'display_name_vi', '') or str(o.pk)) if o else ''


class InboundLineSerializer(serializers.ModelSerializer):
    part_name = serializers.SerializerMethodField()

    class Meta:
        model  = InboundLine
        fields = ['id', 'part', 'torch', 'part_name', 'qty_expected', 'qty_received',
                  'target_bin', 'lot_no', 'lot_expires', 'unit_cost', 'serials_raw', 'order_idx']

    def get_part_name(self, obj) -> str:
        return _line_item_name(obj)


class InboundOrderSerializer(serializers.ModelSerializer):
    lines = InboundLineSerializer(many=True, required=False)
    po_code = serializers.CharField(source='purchase_order.code', read_only=True, default='')

    class Meta:
        model  = InboundOrder
        fields = ['id', 'code', 'warehouse', 'asn', 'purchase_order', 'po_code', 'status',
                  'supplier', 'invoice_no', 'shortage_note', 'received_at', 'lines', 'notes',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'status', 'received_at', 'created_at', 'updated_at']
        # code: nếu client không gửi → view tự sinh (IN-YYYY-NNN).
        extra_kwargs = {'code': {'required': False}}

    def create(self, validated_data):
        lines = validated_data.pop('lines', [])
        order = InboundOrder.objects.create(**validated_data)
        InboundLine.objects.bulk_create([InboundLine(inbound=order, **l) for l in lines])
        return order

    def update(self, instance, validated_data):
        # Chỉ sửa phiếu NHÁP (chưa nhận) — phiếu đã nhận khóa để tránh lệch tồn.
        if instance.status != 'draft':
            raise serializers.ValidationError('Chỉ sửa được phiếu Nháp (chưa nhận hàng).')
        lines = validated_data.pop('lines', None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        if lines is not None:   # thay toàn bộ dòng (draft chưa nhận nên an toàn)
            instance.lines.all().delete()
            InboundLine.objects.bulk_create([InboundLine(inbound=instance, **l) for l in lines])
        return instance


class OutboundLineSerializer(serializers.ModelSerializer):
    part_name = serializers.SerializerMethodField()

    class Meta:
        model  = OutboundLine
        fields = ['id', 'part', 'torch', 'part_name', 'qty_ordered', 'qty_picked', 'order_idx']

    def get_part_name(self, obj) -> str:
        return _line_item_name(obj)


class OutboundOrderSerializer(serializers.ModelSerializer):
    lines = OutboundLineSerializer(many=True, required=False)

    class Meta:
        model  = OutboundOrder
        fields = ['id', 'code', 'warehouse', 'sales_order_code', 'customer',
                  'rule', 'status', 'shipped_at', 'lines', 'notes',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'status', 'shipped_at', 'created_at', 'updated_at']
        # code: nếu client không gửi → view tự sinh (OUT-YYYY-NNN).
        extra_kwargs = {'code': {'required': False}}

    def create(self, validated_data):
        lines = validated_data.pop('lines', [])
        order = OutboundOrder.objects.create(**validated_data)
        OutboundLine.objects.bulk_create([OutboundLine(outbound=order, **l) for l in lines])
        return order


class PickListItemSerializer(serializers.ModelSerializer):
    bin_code = serializers.CharField(source='bin.full_code', read_only=True)

    class Meta:
        model  = PickListItem
        fields = ['id', 'outbound_line', 'bin', 'bin_code', 'lot', 'serial',
                  'qty', 'is_picked']


class ASNSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ASN
        fields = ['id', 'code', 'warehouse', 'supplier', 'eta', 'is_arrived',
                  'notes', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_arrived', 'created_at', 'updated_at']


# ─── Action payloads ─────────────────────────────────────────────────────────
class AdjustSerializer(serializers.Serializer):
    bin     = serializers.PrimaryKeyRelatedField(queryset=Bin.objects.all())
    part    = serializers.CharField(required=False, allow_null=True)
    torch   = serializers.CharField(required=False, allow_null=True)
    new_qty = serializers.IntegerField(min_value=0)
    reason  = serializers.CharField(required=False, default='adjust')
    note    = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        if bool(attrs.get('part')) == bool(attrs.get('torch')):
            raise serializers.ValidationError("Phải có đúng một trong part hoặc torch.")
        return attrs


class TransferSerializer(serializers.Serializer):
    from_bin = serializers.PrimaryKeyRelatedField(queryset=Bin.objects.all())
    to_bin   = serializers.PrimaryKeyRelatedField(queryset=Bin.objects.all())
    part     = serializers.CharField(required=False, allow_null=True)
    torch    = serializers.CharField(required=False, allow_null=True)
    qty      = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        if attrs['from_bin'] == attrs['to_bin']:
            raise serializers.ValidationError("Bin nguồn và đích phải khác nhau.")
        if bool(attrs.get('part')) == bool(attrs.get('torch')):
            raise serializers.ValidationError("Phải có đúng một trong part hoặc torch.")
        return attrs
