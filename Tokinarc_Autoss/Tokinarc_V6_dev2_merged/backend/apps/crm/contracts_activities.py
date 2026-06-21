"""
Tokinarc V6 — apps/crm/contracts_activities.py

API Hợp đồng (Contract) + Hoạt động (Activity). Ownership: sale chỉ thấy bản ghi
của KH mình; manager/admin thấy hết. owner set từ request.user.
Contract code sinh tự động 'HD-XXXX' ở server.
"""
from __future__ import annotations

from rest_framework import filters, serializers, viewsets
from django_filters.rest_framework import DjangoFilterBackend

from apps.accounts.roles import is_manager

from .models import Activity, Contract
from .permissions import CustomerPermission, IsAuthenticatedWithRole


def _next_contract_code() -> str:
    last = Contract.all_objects.order_by('-created_at').first() if hasattr(Contract, 'all_objects') \
        else Contract.objects.order_by('-created_at').first()
    n = 1
    if last and last.code.startswith('HD-'):
        try:
            n = int(last.code.split('-')[1]) + 1
        except (IndexError, ValueError):
            n = 1
    return f"HD-{n:04d}"


# ── Contract ────────────────────────────────────────────────────────────────
class ContractSerializer(serializers.ModelSerializer):
    customer_name  = serializers.CharField(source='customer.name', read_only=True)
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    debt_vnd       = serializers.SerializerMethodField()

    class Meta:
        model = Contract
        fields = [
            'id', 'code', 'customer', 'customer_name', 'quote', 'title',
            'value_vnd', 'paid_vnd', 'debt_vnd', 'status', 'status_display',
            'start_date', 'end_date', 'owner', 'owner_username', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'code', 'owner', 'created_at', 'updated_at']

    def get_debt_vnd(self, obj) -> int:
        return int(obj.value_vnd - obj.paid_vnd)


class ContractViewSet(viewsets.ModelViewSet):
    serializer_class   = ContractSerializer
    permission_classes = [CustomerPermission]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields   = ['status', 'customer']
    search_fields      = ['code', 'customer__name', 'title']

    def get_queryset(self):
        qs = Contract.objects.select_related('customer', 'owner')
        u = self.request.user
        return qs if is_manager(u) else qs.filter(customer__owner_id=u.id)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user, code=_next_contract_code())


# ── Activity ──────────────────────────────────────────────────────────────
class ActivitySerializer(serializers.ModelSerializer):
    customer_name        = serializers.CharField(source='customer.name', read_only=True)
    owner_username       = serializers.CharField(source='owner.username', read_only=True)
    activity_type_display = serializers.CharField(source='get_activity_type_display', read_only=True)
    recording_info  = serializers.SerializerMethodField()
    recap_file_info = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = [
            'id', 'customer', 'customer_name', 'opportunity',
            'activity_type', 'activity_type_display',
            'content', 'activity_date', 'owner', 'owner_username',
            'recording', 'recap_file', 'recap_text', 'recording_info', 'recap_file_info',
            'created_at',
        ]
        read_only_fields = ['id', 'owner', 'created_at']

    def get_recording_info(self, obj):
        from .serializers_ext import _file_info
        return _file_info(obj.recording)

    def get_recap_file_info(self, obj):
        from .serializers_ext import _file_info
        return _file_info(obj.recap_file)


class ActivityViewSet(viewsets.ModelViewSet):
    serializer_class   = ActivitySerializer
    permission_classes = [IsAuthenticatedWithRole]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields   = ['activity_type', 'customer', 'opportunity']
    search_fields      = ['content', 'customer__name']

    def get_queryset(self):
        qs = Activity.objects.select_related('customer', 'owner')
        u = self.request.user
        return qs if is_manager(u) else qs.filter(customer__owner_id=u.id)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
