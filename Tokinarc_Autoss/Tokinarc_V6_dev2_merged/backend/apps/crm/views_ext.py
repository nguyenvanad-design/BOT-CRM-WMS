"""
Tokinarc V6.C-fix3 — apps/crm/views_ext.py

ViewSet cho CRM mở rộng. Kích hoạt các endpoint mà chatbot/tool_clients.py gọi:
    POST /api/v1/crm/quotes/                    create_quote
    POST /api/v1/crm/quotes/{id}/approve/       approve_quote
    POST /api/v1/crm/quotes/{id}/to-contract/   quote_to_contract
    POST /api/v1/crm/opportunities/{id}/move-stage/  move_opportunity_stage
    POST /api/v1/crm/visits/                    create_visit
    POST /api/v1/crm/tickets/                   create_ticket

Quy tắc:
  - owner/created_owner set từ request.user (không tin body).
  - total_vnd của Quote do serializer tính từ lines.
  - approve_quote: chỉ manager/admin (self-approve check); ghi AuditLog.
  - Ownership filter: sale chỉ thấy bản ghi của mình; manager+ thấy hết.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.roles import is_ceo, is_manager, role_of
from apps.common.models import AuditLog

from .models import (
    Lead, Opportunity, OppStage, Quote, QuoteStatus, Ticket, Visit,
)
from .permissions import CustomerPermission, IsAuthenticatedWithRole
from .serializers_ext import (
    LeadSerializer, MoveStageSerializer, OpportunitySerializer,
    QuoteSerializer, TicketSerializer, VisitSerializer,
)


def _audit(request, act, entity, entity_id, diff=None):
    via = 'bot' if request.headers.get('X-Via') == 'bot' else 'ui'
    AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=act, entity=entity, entity_id=str(entity_id),
        diff=diff or {}, via=via,
    )


def _own_filter(qs, user, field='owner_id'):
    """Sale chỉ thấy bản ghi của mình; manager+ thấy hết."""
    if is_manager(user):
        return qs
    return qs.filter(**{field: user.id})


def _next_code(model, prefix):
    """Sinh code tăng dần: prefix-0001. Đơn giản, đủ cho dev (prod nên dùng sequence)."""
    last = model.all_objects.order_by('-created_at').first() if hasattr(model, 'all_objects') \
        else model.objects.order_by('-created_at').first()
    n = 1
    if last and getattr(last, 'code', '').startswith(prefix + '-'):
        try:
            n = int(last.code.split('-')[1]) + 1
        except (IndexError, ValueError):
            n = 1
    return f"{prefix}-{n:04d}"


class LeadViewSet(viewsets.ModelViewSet):
    serializer_class   = LeadSerializer
    permission_classes = [CustomerPermission]

    def get_queryset(self):
        return _own_filter(Lead.objects.all(), self.request.user)

    def perform_create(self, serializer):
        obj = serializer.save(owner=self.request.user)
        _audit(self.request, 'create', 'Lead', obj.id)

    @action(detail=True, methods=['post'])
    def convert(self, request, pk=None):
        """Chuyển Lead → Customer (tạo nhanh, link ngược)."""
        from .models import Customer, CustomerStatus
        lead = self.get_object()
        if lead.converted_customer_id:
            return Response({'detail': 'Lead đã được chuyển.'}, status=400)
        cust = Customer.objects.create(
            code=_next_code(Customer, 'KH'),
            name=lead.company or lead.name,
            status=CustomerStatus.POTENTIAL,
            owner=request.user,
        )
        lead.converted_customer = cust
        lead.status = 'converted'
        lead.save(update_fields=['converted_customer', 'status'])
        _audit(request, 'convert', 'Lead', lead.id, {'customer': str(cust.id)})
        return Response({'customer_id': str(cust.id), 'customer_code': cust.code})


class OpportunityViewSet(viewsets.ModelViewSet):
    serializer_class   = OpportunitySerializer
    permission_classes = [CustomerPermission]

    def get_queryset(self):
        return _own_filter(Opportunity.objects.all(), self.request.user)

    def perform_create(self, serializer):
        obj = serializer.save(owner=self.request.user)
        _audit(self.request, 'create', 'Opportunity', obj.id)

    @action(detail=True, methods=['post'], url_path='move-stage')
    def move_stage(self, request, pk=None):
        opp = self.get_object()
        ser = MoveStageSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_stage = ser.validated_data['stage']
        old_stage = opp.stage
        opp.stage = new_stage
        opp.save(update_fields=['stage', 'updated_at'])
        _audit(request, 'move_stage', 'Opportunity', opp.id,
               {'from': old_stage, 'to': new_stage})
        return Response(OpportunitySerializer(opp).data)


class QuoteViewSet(viewsets.ModelViewSet):
    serializer_class   = QuoteSerializer
    permission_classes = [CustomerPermission]

    def get_queryset(self):
        return _own_filter(Quote.objects.all(), self.request.user)

    def perform_create(self, serializer):
        obj = serializer.save(owner=self.request.user, code=_next_code(Quote, 'BG'))
        _audit(self.request, 'create', 'Quote', obj.id, {'total_vnd': str(obj.total_vnd)})

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Duyệt cấp 1 (manager/CEO/admin).

        - Báo giá dưới ngưỡng → APPROVED luôn.
        - Báo giá ≥ ngưỡng → PENDING_CEO (chờ CEO duyệt cấp 2).
        - Chống tự duyệt: người tạo không tự duyệt (trừ admin).
        """
        quote = self.get_object()
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý/CEO/admin được duyệt báo giá.'},
                            status=status.HTTP_403_FORBIDDEN)
        if quote.owner_id == request.user.id and role_of(request.user) != 'admin':
            return Response({'detail': 'Không tự duyệt báo giá của chính mình.'},
                            status=status.HTTP_403_FORBIDDEN)
        if quote.status not in (QuoteStatus.DRAFT, QuoteStatus.SENT):
            return Response({'detail': f'Báo giá ở trạng thái {quote.status}, không thể duyệt cấp 1.'},
                            status=400)
        now = timezone.now()
        quote.l1_approved_by = request.user
        quote.l1_approved_at = now
        if quote.requires_l2():
            quote.status = QuoteStatus.PENDING_CEO
            fields = ['status', 'l1_approved_by', 'l1_approved_at', 'updated_at']
            _audit(request, 'approve_l1', 'Quote', quote.id, {'next': 'pending_ceo'})
        else:
            quote.status = QuoteStatus.APPROVED
            quote.approved_by = request.user
            fields = ['status', 'l1_approved_by', 'l1_approved_at', 'approved_by', 'updated_at']
            _audit(request, 'approve', 'Quote', quote.id, {'level': 1})
        quote.save(update_fields=fields)
        return Response(QuoteSerializer(quote).data)

    @action(detail=True, methods=['post'], url_path='approve-l2')
    def approve_l2(self, request, pk=None):
        """Duyệt cấp 2 (CEO/admin) cho báo giá vượt ngưỡng đang PENDING_CEO."""
        quote = self.get_object()
        if not is_ceo(request.user):
            return Response({'detail': 'Chỉ CEO/admin được duyệt cấp 2.'},
                            status=status.HTTP_403_FORBIDDEN)
        if quote.status != QuoteStatus.PENDING_CEO:
            return Response({'detail': f'Báo giá ở trạng thái {quote.status}, không chờ CEO duyệt.'},
                            status=400)
        # Chống tự duyệt: người tạo / người đã duyệt cấp 1 không tự duyệt cấp 2 (trừ admin).
        if role_of(request.user) != 'admin' and request.user.id in (quote.owner_id, quote.l1_approved_by_id):
            return Response({'detail': 'Người tạo/đã duyệt cấp 1 không tự duyệt cấp 2.'},
                            status=status.HTTP_403_FORBIDDEN)
        now = timezone.now()
        quote.status = QuoteStatus.APPROVED
        quote.l2_approved_by = request.user
        quote.l2_approved_at = now
        quote.approved_by = request.user
        quote.save(update_fields=['status', 'l2_approved_by', 'l2_approved_at',
                                  'approved_by', 'updated_at'])
        _audit(request, 'approve', 'Quote', quote.id, {'level': 2})
        return Response(QuoteSerializer(quote).data)

    @action(detail=True, methods=['post'], url_path='to-contract')
    def to_contract(self, request, pk=None):
        quote = self.get_object()
        if quote.status != QuoteStatus.APPROVED:
            return Response({'detail': 'Chỉ báo giá đã duyệt mới chuyển hợp đồng.'},
                            status=400)
        # Loose link: tạo mã hợp đồng, gắn vào quote. SalesOrder thật do sales app
        # tạo qua flow riêng (tránh circular import crm→sales).
        order_code = _next_code_simple('HD', Quote, 'contract_order_code')
        quote.contract_order_code = order_code
        quote.status = QuoteStatus.CONVERTED
        quote.save(update_fields=['contract_order_code', 'status', 'updated_at'])
        _audit(request, 'to_contract', 'Quote', quote.id, {'order_code': order_code})
        return Response({'contract_order_code': order_code,
                         'quote': QuoteSerializer(quote).data})


def _next_code_simple(prefix, model, field):
    last = model.objects.exclude(**{field: ''}).order_by('-created_at').first()
    n = 1
    if last and getattr(last, field, '').startswith(prefix + '-'):
        try:
            n = int(getattr(last, field).split('-')[1]) + 1
        except (IndexError, ValueError):
            n = 1
    return f"{prefix}-{n:04d}"


class VisitViewSet(viewsets.ModelViewSet):
    serializer_class   = VisitSerializer
    permission_classes = [CustomerPermission]
    filter_backends    = [DjangoFilterBackend]
    filterset_fields   = ['customer', 'opportunity']

    def get_queryset(self):
        return _own_filter(Visit.objects.all(), self.request.user)

    def perform_create(self, serializer):
        obj = serializer.save(owner=self.request.user)
        _audit(self.request, 'create', 'Visit', obj.id)


class TicketViewSet(viewsets.ModelViewSet):
    serializer_class   = TicketSerializer
    permission_classes = [IsAuthenticatedWithRole]   # service cũng tạo được ticket

    def get_queryset(self):
        # Service/manager+ thấy hết; sale chỉ ticket của KH mình tạo.
        qs = Ticket.objects.all()
        u = self.request.user
        if is_manager(u) or role_of(u) == 'service':
            return qs
        return qs.filter(created_owner_id=u.id)

    def perform_create(self, serializer):
        obj = serializer.save(created_owner=self.request.user,
                              code=_next_code(Ticket, 'TK'))
        _audit(self.request, 'create', 'Ticket', obj.id)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        ticket = self.get_object()
        ticket.status = 'resolved'
        ticket.resolved_at = timezone.now()
        ticket.save(update_fields=['status', 'resolved_at', 'updated_at'])
        _audit(request, 'resolve', 'Ticket', ticket.id)
        return Response(TicketSerializer(ticket).data)
