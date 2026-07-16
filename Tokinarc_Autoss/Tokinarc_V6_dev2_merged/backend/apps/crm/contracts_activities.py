"""
Tokinarc V6 — apps/crm/contracts_activities.py

API Hợp đồng (Contract) + Hoạt động (Activity). Ownership: sale chỉ thấy bản ghi
của KH mình; manager/admin thấy hết. owner set từ request.user.
Contract code sinh tự động 'HD-XXXX' ở server.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import filters, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from apps.accounts.roles import CEO_ROLES, MANAGER_ROLES, is_ceo, is_manager, role_of
from apps.common.models import AuditLog, notify, notify_roles

from .models import Activity, Contract, ContractStatus
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
    requires_l2    = serializers.SerializerMethodField()

    class Meta:
        model = Contract
        fields = [
            'id', 'code', 'customer', 'customer_name', 'quote', 'title',
            'discount_pct', 'value_vnd', 'paid_vnd', 'debt_vnd', 'status', 'status_display',
            'start_date', 'end_date', 'owner', 'owner_username', 'notes',
            'requires_l2', 'l1_approved_by', 'l2_approved_by', 'approved_by',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'code', 'owner', 'l1_approved_by', 'l2_approved_by',
                            'approved_by', 'created_at', 'updated_at']

    def get_debt_vnd(self, obj) -> int:
        return int(obj.value_vnd - obj.paid_vnd)

    def get_requires_l2(self, obj) -> bool:
        return obj.requires_l2()


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
        obj = serializer.save(owner=self.request.user, code=_next_contract_code())
        if obj.status != ContractStatus.DRAFT:
            return
        # Định tuyến duyệt theo % chiết khấu.
        if obj.within_sale_authority():
            obj.approved_by = self.request.user
            obj.status = ContractStatus.PENDING   # ≤ hạn mức sale → tự duyệt → chờ ký
            obj.save(update_fields=['status', 'approved_by', 'updated_at'])
            notify(obj.owner, 'contract_approved',
                   f"Hợp đồng {obj.code} (CK {obj.discount_pct}%) tự duyệt — chuyển bước ký.",
                   link='/contracts')
        else:
            notify_roles(MANAGER_ROLES, 'contract_approval',
                         f"Hợp đồng {obj.code} ({obj.customer.name}) — chiết khấu {obj.discount_pct}% cần duyệt.",
                         link='/ceo/approvals', exclude_user=self.request.user)

    def perform_update(self, serializer):
        """Báo người tạo khi HĐ chuyển sang HIỆU LỰC (đã ký xong)."""
        old_status = serializer.instance.status
        obj = serializer.save()
        if old_status != ContractStatus.ACTIVE and obj.status == ContractStatus.ACTIVE:
            notify(obj.owner, 'contract_active',
                   f"Hợp đồng {obj.code} đã ký, có hiệu lực — theo dõi giao hàng & thu tiền.",
                   link='/contracts')

    def _finalize_approved(self, c, request):
        """Duyệt xong → chuyển 'Chờ ký'; báo người tạo."""
        c.approved_by = request.user
        c.status = ContractStatus.PENDING
        c.save(update_fields=['status', 'approved_by', 'updated_at'])
        notify(c.owner, 'contract_approved',
               f"Hợp đồng {c.code} đã được duyệt — chuyển bước ký.", link='/contracts')

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Duyệt cấp 1 (manager+). Vượt ngưỡng → chờ CEO duyệt cấp 2."""
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý/CEO/admin được duyệt hợp đồng.'}, status=403)
        c = self.get_object()
        if c.status != ContractStatus.DRAFT:
            return Response({'detail': 'Chỉ duyệt được hợp đồng nháp.', 'code': 'CONFLICT'}, status=409)
        now = timezone.now()
        c.l1_approved_by = request.user
        c.l1_approved_at = now
        if c.requires_l2():
            c.status = ContractStatus.PENDING_CEO
            c.save(update_fields=['status', 'l1_approved_by', 'l1_approved_at', 'updated_at'])
            notify_roles(CEO_ROLES, 'contract_approval',
                         f"Hợp đồng {c.code} ({c.customer.name}) chờ CEO duyệt cấp 2.",
                         link='/ceo/approvals')
            AuditLog.record(user=request.user, action='approve_l1', entity='crm.Contract',
                            entity_id=c.id, diff={'next': 'pending_ceo'})
        else:
            c.save(update_fields=['l1_approved_by', 'l1_approved_at', 'updated_at'])
            self._finalize_approved(c, request)
            AuditLog.record(user=request.user, action='approve', entity='crm.Contract',
                            entity_id=c.id, diff={'level': 1})
        return Response(ContractSerializer(c).data)

    @action(detail=True, methods=['post'], url_path='approve-l2')
    def approve_l2(self, request, pk=None):
        """Duyệt cấp 2 (CEO/admin) cho hợp đồng vượt ngưỡng đang chờ."""
        c = self.get_object()
        if not is_ceo(request.user):
            return Response({'detail': 'Chỉ CEO/admin được duyệt cấp 2.'}, status=403)
        if c.status != ContractStatus.PENDING_CEO:
            return Response({'detail': f'Hợp đồng ở trạng thái {c.status}, không chờ CEO duyệt.',
                             'code': 'CONFLICT'}, status=409)
        if role_of(request.user) != 'admin' and request.user.id in (c.owner_id, c.l1_approved_by_id):
            return Response({'detail': 'Không thể tự duyệt cấp 2 hợp đồng mình tạo/đã duyệt cấp 1.'}, status=403)
        c.l2_approved_by = request.user
        c.l2_approved_at = timezone.now()
        c.save(update_fields=['l2_approved_by', 'l2_approved_at', 'updated_at'])
        self._finalize_approved(c, request)
        AuditLog.record(user=request.user, action='approve', entity='crm.Contract',
                        entity_id=c.id, diff={'level': 2})
        return Response(ContractSerializer(c).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Từ chối hợp đồng (manager+) kèm lý do; báo người tạo."""
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý/CEO/admin được từ chối.'}, status=403)
        c = self.get_object()
        if c.status not in (ContractStatus.DRAFT, ContractStatus.PENDING_CEO):
            return Response({'detail': 'Chỉ từ chối được hợp đồng đang chờ duyệt.', 'code': 'CONFLICT'}, status=409)
        reason = str(request.data.get('reason', '')).strip()
        c.status = ContractStatus.REJECTED
        if reason:
            c.notes = (c.notes + f'\n[Từ chối] {reason}').strip()
        c.save(update_fields=['status', 'notes', 'updated_at'])
        notify(c.owner, 'contract_rejected',
               f"Hợp đồng {c.code} bị từ chối. {reason}".strip(), link='/contracts')
        AuditLog.record(user=request.user, action='reject', entity='crm.Contract',
                        entity_id=c.id, diff={'reason': reason})
        return Response(ContractSerializer(c).data)

    @action(detail=False, methods=['get'], url_path='pending-approvals')
    def pending_approvals(self, request):
        """Hợp đồng đang chờ duyệt cho trang Duyệt tập trung (manager+ thấy tất cả)."""
        qs = (self.get_queryset()
              .filter(status__in=[ContractStatus.DRAFT, ContractStatus.PENDING_CEO])
              .order_by('-created_at'))
        return Response({'results': ContractSerializer(qs, many=True).data, 'count': qs.count()})

    @action(detail=True, methods=['get'], url_path='export-docx')
    def export_docx(self, request, pk=None):
        """Xuất hợp đồng ra Word (.docx) — mẫu hợp đồng mua bán có letterhead AUTOSS."""
        from django.http import HttpResponse

        from apps.common.docx_contract import build_contract_docx
        c = self.get_object()
        data = build_contract_docx(c)
        resp = HttpResponse(
            data,
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        resp['Content-Disposition'] = f'attachment; filename="hop_dong_{c.code}.docx"'
        return resp


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
        obj = serializer.save(owner=self.request.user)
        # KANBAN TỰ ĐỘNG: ghi nhận cuộc gọi/email gắn deal → deal sang Thẩm định.
        if obj.opportunity_id:
            from . import opportunity_flow as oflow
            from .models import OppStage
            oflow.advance(obj.opportunity, OppStage.QUALIFY, self.request.user,
                          source=f'activity:{obj.id}')
