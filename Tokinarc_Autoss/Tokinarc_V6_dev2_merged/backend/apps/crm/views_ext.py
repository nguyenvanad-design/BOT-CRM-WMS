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

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.roles import CEO_ROLES, MANAGER_ROLES, is_ceo, is_manager, role_of
from apps.common.models import AuditLog, notify, notify_roles

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
    """Sinh code tăng dần: prefix-0001. Lấy theo MÃ LỚN NHẤT (không theo created_at,
    tránh trùng khi thứ tự tạo ≠ thứ tự mã). Đủ cho dev; prod nên dùng sequence."""
    mgr = model.all_objects if hasattr(model, 'all_objects') else model.objects
    last = mgr.filter(code__startswith=f'{prefix}-').order_by('-code').first()
    n = 1
    if last:
        try:
            n = int(last.code.rsplit('-', 1)[1]) + 1
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
    def assign(self, request, pk=None):
        """Giao lead cho sale khác (chỉ quản lý+) → báo người nhận."""
        from django.contrib.auth import get_user_model
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý được giao lead.'}, status=403)
        lead = self.get_object()
        owner = get_user_model().objects.filter(pk=request.data.get('owner'), is_active=True).first()
        if owner is None:
            return Response({'detail': 'Người nhận không hợp lệ.'}, status=400)
        lead.owner = owner
        lead.save(update_fields=['owner', 'updated_at'])
        _audit(request, 'assign', 'Lead', lead.id)
        if owner.id != request.user.id:
            notify(owner, 'lead_assigned',
                   f"Bạn được giao lead {lead.name}"
                   + (f" ({lead.phone})" if lead.phone else '') + " — liên hệ khách.",
                   link='/leads')
        return Response(LeadSerializer(lead).data)

    @action(detail=True, methods=['post'])
    def convert(self, request, pk=None):
        """Chuyển Lead → Customer (mang theo SĐT/email/ghi chú + tạo người liên hệ)."""
        from django.db import transaction

        from .models import Contact, Customer, CustomerStatus
        lead = self.get_object()
        if lead.converted_customer_id:
            return Response({'detail': 'Lead đã được chuyển.'}, status=400)
        notes = lead.notes
        if lead.referred_by:
            notes = (f"Người giới thiệu: {lead.referred_by}\n{notes}").strip()
        with transaction.atomic():
            cust = Customer.objects.create(
                code=_next_code(Customer, 'KH'),
                name=lead.company or lead.name,
                status=CustomerStatus.POTENTIAL,
                owner=request.user,
                notes=notes,
            )
            # Giữ lại SĐT/email: tạo người liên hệ đầu tiên cho KH.
            if lead.name or lead.phone or lead.email:
                Contact.objects.create(
                    customer=cust,
                    full_name=lead.name or (lead.company or 'Liên hệ'),
                    phone=lead.phone,
                    email=lead.email,
                    is_primary=True,
                    created_by=request.user, updated_by=request.user,
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

    @action(detail=False, methods=['get'])
    def forecast(self, request):
        """Forecast pipeline theo phạm vi của user (sale: của mình; manager+: tất cả).
        weighted = est_value_vnd × probability/100, gộp theo stage."""
        from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum

        qs = _own_filter(Opportunity.objects.exclude(stage__in=['won', 'lost']),
                         request.user)
        weighted = ExpressionWrapper(F('est_value_vnd') * F('probability') / 100.0,
                                     output_field=DecimalField(max_digits=18, decimal_places=2))
        rows = (qs.values('stage')
                .annotate(weighted_vnd=Sum(weighted), total_vnd=Sum('est_value_vnd'),
                          count=Count('id')).order_by('stage'))
        rows = list(rows)
        return Response({
            'by_stage': rows,
            'weighted_total': sum(float(r['weighted_vnd'] or 0) for r in rows),
            'value_total': sum(float(r['total_vnd'] or 0) for r in rows),
            'open_count': sum(int(r['count']) for r in rows),
        })

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
        # Hạn hiệu lực mặc định = hôm nay + QUOTE_VALID_DAYS (nếu chưa nhập).
        extra = {'owner': self.request.user, 'code': _next_code(Quote, 'BG')}
        if not serializer.validated_data.get('valid_until'):
            from datetime import timedelta
            days = getattr(settings, 'QUOTE_VALID_DAYS', 30)
            extra['valid_until'] = timezone.now().date() + timedelta(days=days)
        obj = serializer.save(**extra)
        _audit(self.request, 'create', 'Quote', obj.id, {'discount_pct': str(obj.discount_pct)})
        # Định tuyến duyệt theo % chiết khấu.
        if obj.within_sale_authority():
            # ≤ hạn mức sale → tự động duyệt, sale dùng ngay.
            obj.status = QuoteStatus.APPROVED
            obj.approved_by = self.request.user
            obj.save(update_fields=['status', 'approved_by', 'updated_at'])
            notify(self.request.user, 'quote_approved',
                   f"Báo giá {obj.code} (CK {obj.discount_pct}%) tự duyệt — trong hạn mức sale.",
                   link='/quotes')
        else:
            # > hạn mức sale → cần manager (và CEO nếu vượt hạn mức manager).
            notify_roles(MANAGER_ROLES, 'quote_approval',
                         f"Báo giá {obj.code} ({obj.customer.name}) — chiết khấu {obj.discount_pct}% cần duyệt.",
                         link='/ceo/approvals', exclude_user=self.request.user)

    @action(detail=False, methods=['get'], url_path='pending-approvals')
    def pending_approvals(self, request):
        """Hàng chờ duyệt cho trang Duyệt tập trung (manager+ thấy tất cả).

        Trả báo giá đang chờ quyết định để FE tách 2 nhóm:
          - cấp 1: draft/sent   → manager+ duyệt
          - cấp 2: pending_ceo  → CEO duyệt
        get_queryset() đã lọc theo quyền (sale chỉ thấy của mình).
        """
        qs = (self.get_queryset()
              .filter(status__in=[QuoteStatus.DRAFT, QuoteStatus.SENT, QuoteStatus.PENDING_CEO])
              .select_related('customer')
              .order_by('-created_at'))
        ser = QuoteSerializer(qs, many=True, context={'request': request})
        return Response({'results': ser.data, 'count': qs.count()})

    @action(detail=True, methods=['get'], url_path='export-xlsx')
    def export_xlsx(self, request, pk=None):
        """Xuất báo giá ra Excel dạng chứng từ (đầu trang thông tin KH + bảng dòng)."""
        from apps.common.company import vnd_to_words
        from apps.common.excel import customer_party, make_document_xlsx, xlsx_response
        q = self.get_object()
        rows = [(l.part_no, l.part_name or '', l.qty, int(l.unit_price_vnd or 0),
                 int(l.qty * (l.unit_price_vnd or 0))) for l in q.lines.all()]
        sub = int(q.subtotal_vnd)
        disc = float(q.discount_pct or 0)
        extra = [('Tạm tính', sub),
                 (f'Chiết khấu {disc:g}%', -(sub - int(q.total_vnd or 0)))] if disc > 0 else None
        data = make_document_xlsx(
            sheet_title='BaoGia', doc_title='BÁO GIÁ', doc_code=q.code,
            doc_date=q.created_at.strftime('%d/%m/%Y'),
            party_label='KÍNH GỬI (KHÁCH HÀNG):', party=customer_party(q.customer),
            meta=[('Trạng thái:', q.get_status_display()),
                  ('Hạn hiệu lực:', q.valid_until.strftime('%d/%m/%Y') if q.valid_until else '—')],
            columns=[('Mã part', 16, 'text'), ('Tên hàng', 40, 'text'), ('SL', 8, 'int'),
                     ('Đơn giá', 16, 'money'), ('Thành tiền', 18, 'money')],
            rows=rows, extra_totals=extra,
            total_label='TỔNG CỘNG', total_value=int(q.total_vnd or 0),
            amount_words=vnd_to_words(q.total_vnd),
            signatures=['NGƯỜI LẬP BÁO GIÁ', 'XÁC NHẬN KHÁCH HÀNG'])
        return xlsx_response(data, f'bao_gia_{q.code}.xlsx')

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
            notify_roles(CEO_ROLES, 'quote_approval',
                         f"Báo giá {quote.code} ({quote.customer.name}) chờ CEO duyệt cấp 2.",
                         link='/quotes', exclude_user=request.user)
        else:
            quote.status = QuoteStatus.APPROVED
            quote.approved_by = request.user
            fields = ['status', 'l1_approved_by', 'l1_approved_at', 'approved_by', 'updated_at']
            _audit(request, 'approve', 'Quote', quote.id, {'level': 1})
            notify(quote.owner, 'quote_approved', f"Báo giá {quote.code} đã được duyệt.", link='/quotes')
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
        notify(quote.owner, 'quote_approved',
               f"Báo giá {quote.code} đã được CEO duyệt (cấp 2).", link='/quotes')
        return Response(QuoteSerializer(quote).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Từ chối báo giá kèm lý do (manager/CEO/admin). Lưu lý do vào notes + audit."""
        quote = self.get_object()
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý/CEO/admin được từ chối báo giá.'},
                            status=status.HTTP_403_FORBIDDEN)
        if quote.status not in (QuoteStatus.DRAFT, QuoteStatus.SENT, QuoteStatus.PENDING_CEO):
            return Response({'detail': f'Báo giá ở trạng thái {quote.status}, không thể từ chối.'},
                            status=400)
        reason = (request.data.get('reason') or '').strip()
        quote.status = QuoteStatus.REJECTED
        if reason:
            quote.notes = (quote.notes + f"\n[Từ chối] {reason}").strip()
        quote.save(update_fields=['status', 'notes', 'updated_at'])
        _audit(request, 'reject', 'Quote', quote.id, {'reason': reason})
        notify(quote.owner, 'quote_rejected',
               f"Báo giá {quote.code} bị từ chối" + (f": {reason}" if reason else "."), link='/quotes')
        return Response(QuoteSerializer(quote).data)

    @staticmethod
    def _is_expired(quote) -> bool:
        return bool(quote.valid_until and quote.valid_until < timezone.now().date())

    @action(detail=True, methods=['post'], url_path='to-contract')
    def to_contract(self, request, pk=None):
        quote = self.get_object()
        if quote.status != QuoteStatus.APPROVED:
            return Response({'detail': 'Chỉ báo giá đã duyệt mới chuyển hợp đồng.'},
                            status=400)
        if self._is_expired(quote):
            return Response({'detail': f'Báo giá đã hết hạn ({quote.valid_until}). '
                             'Cần làm lại báo giá mới.', 'code': 'QUOTE_EXPIRED'}, status=400)
        # Loose link: tạo mã hợp đồng, gắn vào quote. SalesOrder thật do sales app
        # tạo qua flow riêng (tránh circular import crm→sales).
        order_code = _next_code_simple('HD', Quote, 'contract_order_code')
        quote.contract_order_code = order_code
        quote.status = QuoteStatus.CONVERTED
        quote.save(update_fields=['contract_order_code', 'status', 'updated_at'])
        _audit(request, 'to_contract', 'Quote', quote.id, {'order_code': order_code})
        return Response({'contract_order_code': order_code,
                         'quote': QuoteSerializer(quote).data})

    @action(detail=True, methods=['post'], url_path='to-order')
    def to_order(self, request, pk=None):
        """Báo giá ĐÃ DUYỆT → tạo SalesOrder thật (draft) + lines từ QuoteLine."""
        from django.utils import timezone

        from apps.catalog.models import Part
        from apps.sales import services as sales_services
        from apps.sales.models import SalesOrder, SalesOrderLine

        quote = self.get_object()
        if quote.status != QuoteStatus.APPROVED:
            return Response({'detail': 'Chỉ báo giá đã duyệt mới tạo đơn hàng.'}, status=400)
        if self._is_expired(quote):
            return Response({'detail': f'Báo giá đã hết hạn ({quote.valid_until}). '
                             'Cần làm lại báo giá mới.', 'code': 'QUOTE_EXPIRED'}, status=400)
        if quote.contract_order_code:
            return Response({'detail': f'Báo giá đã gắn đơn/HĐ {quote.contract_order_code}.'},
                            status=400)

        year = timezone.now().year
        pre = f'DH-{year}-'
        last = SalesOrder.objects.filter(code__startswith=pre).order_by('-code').first()
        seq = (int(last.code.rsplit('-', 1)[-1]) + 1) if last else 1
        code = f'{pre}{seq:03d}'

        with transaction.atomic():
            order = SalesOrder.objects.create(
                code=code, customer=quote.customer, issued_date=timezone.now().date(),
                owner=quote.owner, created_by=request.user, updated_by=request.user,
                status='draft', payment_terms_note=quote.payment_terms_note,
            )
            for idx, ql in enumerate(quote.lines.all()):
                part = Part.objects.filter(pk=ql.part_no).first()
                SalesOrderLine.objects.create(
                    order=order, part=part, description=ql.part_name or ql.part_no,
                    qty=ql.qty, unit_price=ql.unit_price_vnd,
                    line_total=ql.qty * ql.unit_price_vnd, order_idx=idx,
                )
            sales_services.recompute_order_total(order)
            quote.contract_order_code = code
            quote.status = QuoteStatus.CONVERTED
            quote.save(update_fields=['contract_order_code', 'status', 'updated_at'])
        _audit(request, 'to_order', 'Quote', quote.id, {'order_code': code})
        return Response({'order_code': code, 'order_id': str(order.id),
                         'total_vnd': str(order.total_vnd)})


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
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields   = ['customer', 'opportunity']
    search_fields      = ['code', 'customer__name']

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
        self._notify_assignee(obj, None)

    def perform_update(self, serializer):
        before = serializer.instance.assignee_id
        obj = serializer.save()
        self._notify_assignee(obj, before)

    def _notify_assignee(self, obj, before_assignee_id):
        """Báo kỹ sư khi ticket được giao (mới hoặc đổi assignee), trừ người tự giao."""
        if (obj.assignee_id and obj.assignee_id != before_assignee_id
                and obj.assignee_id != self.request.user.id):
            notify(obj.assignee, 'ticket_assigned',
                   f"Bạn được giao ticket {obj.code}: {obj.title}", link='/tickets')

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        """Kỹ sư NHẬN xử lý: open → in_progress; tự gán mình nếu ticket chưa có người."""
        ticket = self.get_object()
        if ticket.status not in ('open', 'in_progress'):
            return Response({'detail': 'Ticket đã giải quyết/đóng.', 'code': 'CONFLICT'}, status=409)
        ticket.status = 'in_progress'
        fields = ['status', 'updated_at']
        if ticket.assignee_id is None:
            ticket.assignee = request.user
            fields.append('assignee')
        ticket.save(update_fields=fields)
        _audit(request, 'accept', 'Ticket', ticket.id)
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Giải quyết: ghi CÁCH XỬ LÝ + báo người tạo ticket."""
        ticket = self.get_object()
        ticket.status = 'resolved'
        ticket.resolved_at = timezone.now()
        res = str(request.data.get('resolution', '')).strip()
        if res:
            ticket.resolution = res
        ticket.save(update_fields=['status', 'resolved_at', 'resolution', 'updated_at'])
        _audit(request, 'resolve', 'Ticket', ticket.id, {'resolution': res[:120]})
        # Báo người tạo ticket: đã xử lý xong.
        if ticket.created_owner_id and ticket.created_owner_id != request.user.id:
            notify(ticket.created_owner, 'ticket_resolved',
                   f"Ticket {ticket.code} ({ticket.customer.name}) đã được xử lý xong.",
                   link='/tickets')
        return Response(TicketSerializer(ticket).data)
