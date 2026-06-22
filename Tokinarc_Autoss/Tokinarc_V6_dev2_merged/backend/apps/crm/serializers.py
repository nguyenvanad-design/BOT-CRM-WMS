"""
Tokinarc V6.C — apps/crm/serializers.py

Pattern minh họa:
  - Nested write-able Contact bên trong Customer (line-items pattern, dùng lại
    cho QuoteLine, SalesOrderLine sau này).
  - Read-only fields với decimal/datetime format chuẩn.
  - validate_*() để check business rule (ví dụ: chỉ 1 primary contact).
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers

from .models import Contact, Customer


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Contact
        fields = [
            'id', 'full_name', 'title', 'phone', 'email',
            'preferred_channel', 'is_primary', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CustomerListSerializer(serializers.ModelSerializer):
    """Compact serializer cho list view — không lấy nested contacts để rẻ query."""
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    contact_count  = serializers.IntegerField(read_only=True)  # gán từ annotate

    class Meta:
        model  = Customer
        fields = [
            'id', 'code', 'name', 'tax_code', 'segment', 'region',
            'status', 'owner', 'owner_username', 'contact_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CustomerDetailSerializer(serializers.ModelSerializer):
    """Detail có nested contacts, dùng cho retrieve + create + update."""
    contacts        = ContactSerializer(many=True, required=False)
    owner_username  = serializers.CharField(source='owner.username', read_only=True)

    class Meta:
        model  = Customer
        fields = [
            'id', 'code', 'name', 'tax_code', 'segment', 'region',
            'address', 'status', 'owner', 'owner_username', 'credit_limit_vnd',
            'contacts', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        # owner do viewset.perform_create gán mặc định = user hiện tại;
        # manager có thể truyền owner trong payload để gán cho sale khác.
        extra_kwargs = {'owner': {'required': False}}

    # ── Validation ──────────────────────────────────────────────────────────
    def validate_contacts(self, value):
        """Tối đa 1 primary contact."""
        if sum(1 for c in value if c.get('is_primary')) > 1:
            raise serializers.ValidationError("Chỉ được có 1 liên hệ chính.")
        return value

    def validate_code(self, value):
        if not value.startswith('KH-'):
            raise serializers.ValidationError("Mã KH phải bắt đầu bằng 'KH-'.")
        return value

    # ── Create with nested ──────────────────────────────────────────────────
    @transaction.atomic
    def create(self, validated_data):
        contacts_data = validated_data.pop('contacts', [])
        customer = Customer.objects.create(**validated_data)
        Contact.objects.bulk_create([
            Contact(customer=customer, **c) for c in contacts_data
        ])
        return customer

    # ── Update with nested (full replacement of contacts) ───────────────────
    @transaction.atomic
    def update(self, instance, validated_data):
        contacts_data = validated_data.pop('contacts', None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        if contacts_data is not None:
            # Diff thay vì wipe để giữ FK reference của Activity/Visit (sau này)
            existing = {str(c.id): c for c in instance.contacts.all()}
            seen     = set()
            for c_data in contacts_data:
                cid = c_data.get('id')
                if cid and str(cid) in existing:
                    obj = existing[str(cid)]
                    for k, v in c_data.items():
                        setattr(obj, k, v)
                    obj.save()
                    seen.add(str(cid))
                else:
                    Contact.objects.create(customer=instance, **c_data)
            # Delete those omitted
            for cid, obj in existing.items():
                if cid not in seen:
                    obj.delete()
        return instance


class Customer360Serializer(serializers.Serializer):
    """
    Aggregated view cho action /360/. Không backed by model — viewset compose
    từ nhiều bảng. Khi sales/quote/wms model có sẵn, mở rộng tại đây.
    """
    customer       = CustomerDetailSerializer(read_only=True)
    open_orders    = serializers.IntegerField(read_only=True)
    debt_vnd       = serializers.DecimalField(max_digits=14, decimal_places=0, read_only=True)
    open_tickets   = serializers.IntegerField(read_only=True)
    last_activity  = serializers.DateTimeField(read_only=True, allow_null=True)
