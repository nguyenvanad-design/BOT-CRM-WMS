"""
Tokinarc V6.C — apps/sales/serializers.py
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers

from . import services
from .models import (
    Invoice, Payment, ReturnLine, ReturnOrder, SalesOrder, SalesOrderLine,
)


class ReturnLineSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source='part.display_name_vi', read_only=True)

    class Meta:
        model = ReturnLine
        fields = ['id', 'part', 'part_name', 'qty', 'unit_price', 'line_total', 'target_bin', 'order_idx']
        read_only_fields = ['id', 'line_total']


class ReturnOrderSerializer(serializers.ModelSerializer):
    lines = ReturnLineSerializer(many=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    warehouse_code = serializers.CharField(source='warehouse.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ReturnOrder
        fields = ['id', 'code', 'order', 'customer', 'customer_name', 'warehouse',
                  'warehouse_code', 'status', 'status_display', 'reason', 'total_vnd',
                  'owner', 'received_at', 'notes', 'lines', 'created_at']
        read_only_fields = ['id', 'code', 'status', 'total_vnd', 'owner', 'received_at', 'created_at']

    @transaction.atomic
    def create(self, validated):
        lines = validated.pop('lines', [])
        ro = ReturnOrder.objects.create(**validated)
        for idx, l in enumerate(lines):
            lt = int(l['qty']) * int(l.get('unit_price', 0))
            ReturnLine.objects.create(ro=ro, part=l['part'], qty=l['qty'],
                                      unit_price=l.get('unit_price', 0), line_total=lt,
                                      target_bin=l.get('target_bin'), order_idx=idx)
        ro.recompute_total(); ro.save(update_fields=['total_vnd'])
        return ro


class InvoiceSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    order_code = serializers.CharField(source='order.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Invoice
        fields = ['id', 'code', 'order', 'order_code', 'customer', 'customer_name',
                  'issue_date', 'subtotal_vnd', 'tax_pct', 'tax_vnd', 'total_vnd',
                  'status', 'status_display', 'notes', 'misa_status', 'misa_ref',
                  'synced_at', 'created_at']
        read_only_fields = ['id', 'code', 'customer', 'subtotal_vnd', 'tax_vnd',
                            'total_vnd', 'status', 'misa_status', 'misa_ref',
                            'synced_at', 'created_at']


class SalesOrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SalesOrderLine
        fields = ['id', 'part', 'torch', 'description', 'qty', 'unit_price',
                  'discount_pct', 'line_total', 'shipped_qty', 'order_idx']
        read_only_fields = ['id', 'line_total', 'shipped_qty']


class SalesOrderListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    debt_vnd      = serializers.DecimalField(max_digits=14, decimal_places=0, read_only=True)

    class Meta:
        model  = SalesOrder
        fields = ['id', 'code', 'customer', 'customer_name', 'order_type',
                  'issued_date', 'total_vnd', 'paid_vnd', 'debt_vnd',
                  'payment_terms', 'payment_terms_note', 'status', 'owner', 'created_at']
        read_only_fields = fields


class SalesOrderDetailSerializer(serializers.ModelSerializer):
    lines    = SalesOrderLineSerializer(many=True)
    debt_vnd = serializers.DecimalField(max_digits=14, decimal_places=0, read_only=True)

    class Meta:
        model  = SalesOrder
        fields = ['id', 'code', 'customer', 'order_type', 'parent_order',
                  'issued_date', 'valid_from', 'valid_to', 'total_vnd', 'paid_vnd',
                  'debt_vnd', 'payment_terms', 'payment_terms_note', 'status', 'owner', 'ship_address',
                  'lines', 'notes', 'created_at', 'updated_at']
        read_only_fields = ['id', 'total_vnd', 'paid_vnd', 'status', 'created_at', 'updated_at']
        extra_kwargs = {'owner': {'required': False}}

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop('lines', [])
        order = SalesOrder.objects.create(**validated_data)
        self._save_lines(order, lines)
        services.recompute_order_total(order)
        return order

    @transaction.atomic
    def update(self, instance, validated_data):
        lines = validated_data.pop('lines', None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        if lines is not None:
            instance.lines.all().delete()
            self._save_lines(instance, lines)
            services.recompute_order_total(instance)
        return instance

    def _save_lines(self, order, lines):
        objs = []
        for idx, l in enumerate(lines):
            lt = services.compute_line_total(l['qty'], l['unit_price'], l.get('discount_pct', 0))
            objs.append(SalesOrderLine(order=order, line_total=lt, order_idx=idx,
                                       **{k: v for k, v in l.items() if k != 'line_total'}))
        SalesOrderLine.objects.bulk_create(objs)


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Payment
        fields = ['id', 'order', 'amount_vnd', 'paid_at', 'method', 'reference',
                  'notes', 'created_at']
        read_only_fields = ['id', 'created_at']
