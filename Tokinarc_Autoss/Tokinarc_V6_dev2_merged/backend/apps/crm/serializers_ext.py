"""
Tokinarc V6.C-fix3 — apps/crm/serializers_ext.py

Serializers cho CRM mở rộng: Lead, Opportunity, Quote(+Line), Visit, Ticket.
Tách riêng khỏi serializers.py (Customer/Contact) để dễ đọc.

Nguyên tắc:
  - total_vnd của Quote tính ở SERVER từ lines, client/bot KHÔNG set được.
  - owner/created_owner set ở view (perform_create), không nhận từ body.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers

from .models import (
    Lead, Opportunity, Quote, QuoteLine, Ticket, Visit,
)


# ── Lead ──────────────────────────────────────────────────────────────────
class LeadSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)

    class Meta:
        model = Lead
        fields = [
            'id', 'name', 'company', 'phone', 'email', 'source', 'source_display',
            'campaign', 'status', 'score', 'owner', 'owner_username',
            'converted_customer', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'owner', 'converted_customer',
                            'created_at', 'updated_at']


# ── Opportunity ───────────────────────────────────────────────────────────
class OpportunitySerializer(serializers.ModelSerializer):
    owner_username   = serializers.CharField(source='owner.username', read_only=True)
    customer_name    = serializers.CharField(source='customer.name', read_only=True)
    stage_display    = serializers.CharField(source='get_stage_display', read_only=True)

    class Meta:
        model = Opportunity
        fields = [
            'id', 'customer', 'customer_name', 'title', 'stage', 'stage_display',
            'est_value_vnd', 'probability', 'expected_close',
            'owner', 'owner_username', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'owner', 'created_at', 'updated_at']


class MoveStageSerializer(serializers.Serializer):
    """Body cho action move-stage."""
    stage = serializers.ChoiceField(choices=Opportunity._meta.get_field('stage').choices)


# ── Quote + QuoteLine ─────────────────────────────────────────────────────
class QuoteLineSerializer(serializers.ModelSerializer):
    line_total_vnd = serializers.SerializerMethodField()

    class Meta:
        model = QuoteLine
        fields = ['id', 'part_no', 'part_name', 'qty', 'unit_price_vnd', 'line_total_vnd']
        read_only_fields = ['id']

    def get_line_total_vnd(self, obj) -> int:
        return int(obj.qty * obj.unit_price_vnd)


class QuoteSerializer(serializers.ModelSerializer):
    lines          = QuoteLineSerializer(many=True)
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    customer_name  = serializers.CharField(source='customer.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    requires_l2    = serializers.SerializerMethodField()

    class Meta:
        model = Quote
        fields = [
            'id', 'code', 'customer', 'customer_name', 'opportunity',
            'status', 'status_display', 'due_date', 'total_vnd', 'requires_l2',
            'owner', 'owner_username', 'approved_by', 'contract_order_code',
            'l1_approved_by', 'l1_approved_at', 'l2_approved_by', 'l2_approved_at',
            'lines', 'notes', 'created_at', 'updated_at',
        ]
        # total_vnd tính ở server; code sinh ở server; owner set ở view.
        read_only_fields = [
            'id', 'code', 'total_vnd', 'owner', 'approved_by',
            'l1_approved_by', 'l1_approved_at', 'l2_approved_by', 'l2_approved_at',
            'contract_order_code', 'status', 'created_at', 'updated_at',
        ]

    def get_requires_l2(self, obj) -> bool:
        return obj.requires_l2()

    @transaction.atomic
    def create(self, validated):
        lines_data = validated.pop('lines', [])
        quote = Quote.objects.create(**validated)
        for ld in lines_data:
            QuoteLine.objects.create(quote=quote, **ld)
        quote.recompute_total()
        quote.save(update_fields=['total_vnd'])
        return quote

    @transaction.atomic
    def update(self, instance, validated):
        lines_data = validated.pop('lines', None)
        for k, v in validated.items():
            setattr(instance, k, v)
        if lines_data is not None:
            instance.lines.all().delete()
            for ld in lines_data:
                QuoteLine.objects.create(quote=instance, **ld)
            instance.recompute_total()
        instance.save()
        return instance


# ── Visit ─────────────────────────────────────────────────────────────────
def _file_info(obj):
    """Tóm tắt FileObject cho FE (tên + link tải)."""
    if not obj:
        return None
    return {'id': str(obj.id), 'filename': obj.filename,
            'download_url': f"/api/v1/storage/files/{obj.id}/download/"}


class VisitSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    customer_name  = serializers.CharField(source='customer.name', read_only=True)
    recording_info  = serializers.SerializerMethodField()
    recap_file_info = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        fields = [
            'id', 'customer', 'customer_name', 'opportunity', 'visit_date', 'purpose',
            'summary', 'next_action', 'gps', 'owner', 'owner_username',
            'recording', 'recap_file', 'recap_text', 'recording_info', 'recap_file_info',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'owner', 'created_at', 'updated_at']

    def get_recording_info(self, obj):
        return _file_info(obj.recording)

    def get_recap_file_info(self, obj):
        return _file_info(obj.recap_file)


# ── Ticket ────────────────────────────────────────────────────────────────
class TicketSerializer(serializers.ModelSerializer):
    customer_name    = serializers.CharField(source='customer.name', read_only=True)
    status_display   = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)

    class Meta:
        model = Ticket
        fields = [
            'id', 'code', 'customer', 'customer_name', 'title', 'description',
            'status', 'status_display', 'priority', 'priority_display',
            'serial_no', 'assignee', 'created_owner', 'resolved_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'code', 'created_owner', 'resolved_at',
            'created_at', 'updated_at',
        ]
