from __future__ import annotations

from django.db import transaction
from rest_framework import serializers

from .models import PurchaseOrder, PurchaseOrderLine, PurchasePayment, Supplier


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ['id', 'code', 'name', 'tax_code', 'phone', 'email', 'address',
                  'notes', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']


class POLineSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source='part.display_name_vi', read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = ['id', 'part', 'part_name', 'description', 'qty', 'unit_cost',
                  'line_total', 'qty_received', 'target_bin', 'order_idx']
        read_only_fields = ['id', 'line_total', 'qty_received']


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = POLineSerializer(many=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    warehouse_code = serializers.CharField(source='warehouse.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    debt_vnd = serializers.IntegerField(read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = ['id', 'code', 'supplier', 'supplier_name', 'warehouse', 'warehouse_code',
                  'status', 'status_display', 'order_date', 'expected_date',
                  'total_vnd', 'paid_vnd', 'debt_vnd', 'owner', 'notes',
                  'received_at', 'lines', 'created_at']
        read_only_fields = ['id', 'code', 'status', 'total_vnd', 'paid_vnd', 'owner',
                            'received_at', 'created_at']

    @transaction.atomic
    def create(self, validated):
        lines = validated.pop('lines', [])
        po = PurchaseOrder.objects.create(**validated)
        self._save_lines(po, lines)
        po.recompute_total(); po.save(update_fields=['total_vnd'])
        return po

    @transaction.atomic
    def update(self, instance, validated):
        lines = validated.pop('lines', None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if lines is not None:
            instance.lines.all().delete()
            self._save_lines(instance, lines)
            instance.recompute_total(); instance.save(update_fields=['total_vnd'])
        return instance

    def _save_lines(self, po, lines):
        for idx, l in enumerate(lines):
            lt = int(l['qty']) * int(l['unit_cost'])
            PurchaseOrderLine.objects.create(
                po=po, part=l['part'], description=l.get('description', ''),
                qty=l['qty'], unit_cost=l['unit_cost'], line_total=lt,
                target_bin=l.get('target_bin'), order_idx=idx)


class PurchasePaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchasePayment
        fields = ['id', 'po', 'amount_vnd', 'paid_at', 'method', 'reference', 'notes', 'created_at']
        read_only_fields = ['id', 'created_at']
