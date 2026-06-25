"""
Tokinarc V6.C — apps/crm/views.py

ViewSet pattern dùng xuyên hệ thống:
  - ModelViewSet với serializer khác cho list vs detail (giảm payload list)
  - perform_create/update set owner + audit
  - Custom @action /360/ aggregate từ nhiều bảng
  - perform_destroy → soft delete thay vì hard delete
  - Filter + search + ordering qua django-filter
"""
from __future__ import annotations

from django.db.models import Count, F, Max, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.models import AuditLog

from .models import Customer
from .permissions import (
    CustomerPermission,
    IsAuthenticatedWithRole,
    filter_customers_for_user,
)
from .serializers import (
    Customer360Serializer,
    CustomerDetailSerializer,
    CustomerListSerializer,
)


class CustomerViewSet(viewsets.ModelViewSet):
    """
    REST endpoints khớp V6.A.3 §3.3:
      GET    /api/v1/crm/customers/
      POST   /api/v1/crm/customers/
      GET    /api/v1/crm/customers/{id}/
      PATCH  /api/v1/crm/customers/{id}/
      DELETE /api/v1/crm/customers/{id}/      (soft delete)
      GET    /api/v1/crm/customers/{id}/360/
    """
    permission_classes = [IsAuthenticatedWithRole, CustomerPermission]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['segment', 'status', 'region', 'owner']
    search_fields      = ['code', 'name', 'tax_code']
    ordering_fields    = ['created_at', 'updated_at', 'name']
    ordering           = ['-created_at']

    def get_queryset(self):
        qs = Customer.objects.select_related('owner')
        qs = filter_customers_for_user(qs, self.request.user)
        if self.action == 'list':
            qs = qs.annotate(contact_count=Count('contacts'))
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return CustomerListSerializer
        if self.action == 'customer_360':
            return Customer360Serializer
        return CustomerDetailSerializer

    # ── Hooks ───────────────────────────────────────────────────────────────
    def perform_create(self, serializer):
        # Mặc định owner = user hiện tại; manager có thể override qua payload
        from .permissions import is_manager
        owner = serializer.validated_data.get('owner') or self.request.user
        if not is_manager(self.request.user):
            owner = self.request.user
        instance = serializer.save(
            owner=owner, created_by=self.request.user, updated_by=self.request.user,
        )
        AuditLog.record(
            user=self.request.user, action='create',
            entity='crm.Customer', entity_id=instance.id,
            diff={'after': serializer.data},
            ip=self._ip(), user_agent=self._ua(),
        )

    def perform_update(self, serializer):
        before = CustomerListSerializer(serializer.instance).data
        instance = serializer.save(updated_by=self.request.user)
        AuditLog.record(
            user=self.request.user, action='update',
            entity='crm.Customer', entity_id=instance.id,
            diff={'before': before, 'after': serializer.data},
            ip=self._ip(), user_agent=self._ua(),
        )

    def perform_destroy(self, instance):
        # Soft delete thay vì hard
        instance.soft_delete(user=self.request.user)
        AuditLog.record(
            user=self.request.user, action='delete',
            entity='crm.Customer', entity_id=instance.id, diff={},
            ip=self._ip(), user_agent=self._ua(),
        )

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        """Giao khách hàng cho sale khác (chỉ quản lý+) → báo người nhận."""
        from django.contrib.auth import get_user_model

        from apps.common.models import notify
        from .permissions import is_manager
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý được giao khách.'}, status=403)
        customer = self.get_object()
        owner = get_user_model().objects.filter(pk=request.data.get('owner'), is_active=True).first()
        if owner is None:
            return Response({'detail': 'Người nhận không hợp lệ.'}, status=400)
        customer.owner = owner
        customer.save(update_fields=['owner', 'updated_at'])
        AuditLog.record(user=request.user, action='assign', entity='crm.Customer',
                        entity_id=customer.id, diff={'owner': owner.username},
                        ip=self._ip(), user_agent=self._ua())
        if owner.id != request.user.id:
            notify(owner, 'customer_assigned',
                   f"Bạn được giao khách hàng {customer.name} — chăm sóc & theo dõi.",
                   link=f'/customers/{customer.id}')
        return Response({'detail': f'Đã giao {customer.name} cho {owner.username}.'})

    # ── /360/ — customer 360 view ────────────────────────────────────────────
    @action(detail=True, methods=['get'], url_path='360', url_name='360')
    def customer_360(self, request, pk=None):
        """
        Aggregate KH từ nhiều bảng: đơn hàng đang mở, công nợ, ticket mở, hoạt
        động gần nhất. Tính THẬT từ apps.sales (SalesOrder) + apps.crm (Ticket/
        Visit/Opportunity/Quote). Import sales lazy để tránh circular import.
        """
        from apps.sales.models import OrderStatus, SalesOrder

        from .models import Opportunity, Quote, Ticket, TicketStatus, Visit

        customer = self.get_object()
        orders = SalesOrder.objects.filter(customer=customer)

        open_orders = orders.filter(
            status__in=[OrderStatus.PENDING, OrderStatus.ACTIVE, OrderStatus.SHIPPING],
        ).count()
        debt_vnd = orders.filter(
            status__in=[OrderStatus.ACTIVE, OrderStatus.SHIPPING, OrderStatus.COMPLETED],
        ).aggregate(d=Sum(F('total_vnd') - F('paid_vnd')))['d'] or 0
        open_tickets = Ticket.objects.filter(
            customer=customer, status__in=[TicketStatus.OPEN, TicketStatus.IN_PROGRESS],
        ).count()

        # Hoạt động gần nhất = updated_at mới nhất trong các bảng liên quan.
        last_activity = None
        for qs in (
            Visit.objects.filter(customer=customer),
            Opportunity.objects.filter(customer=customer),
            Quote.objects.filter(customer=customer),
            Ticket.objects.filter(customer=customer),
            orders,
        ):
            m = qs.aggregate(m=Max('updated_at'))['m']
            if m and (last_activity is None or m > last_activity):
                last_activity = m

        limit = int(customer.credit_limit_vnd or 0)
        payload = {
            'customer':      customer,
            'open_orders':   open_orders,
            'debt_vnd':      debt_vnd,
            'open_tickets':  open_tickets,
            'last_activity': last_activity,
        }
        ser = Customer360Serializer(payload)
        data = ser.data
        data['credit_limit_vnd'] = limit
        data['credit_over'] = bool(limit and debt_vnd > limit)   # vượt hạn mức?
        data['credit_available'] = (limit - debt_vnd) if limit else None
        return Response(data)

    # ── /timeline/ — lịch sử làm việc với khách hàng ─────────────────────────
    @action(detail=True, methods=['get'], url_path='timeline')
    def timeline(self, request, pk=None):
        """Dòng thời gian tương tác: Visit + Activity + Báo giá + Đơn + Ticket.

        Gộp từ nhiều bảng, sắp xếp giảm dần theo thời gian. Tôn trọng ownership
        (sale chỉ xem KH của mình — get_object đã kiểm tra object permission).
        """
        from apps.sales.models import SalesOrder

        from .models import Activity, Quote, Ticket, Visit

        customer = self.get_object()
        events: list[dict] = []

        def _iso(d):
            return d.isoformat() if d else ''

        def _dl(fid):
            return f"/api/v1/storage/files/{fid}/download/" if fid else None

        for v in (Visit.objects.filter(customer=customer)
                  .select_related('owner', 'recording', 'recap_file')[:50]):
            events.append({
                'date': _iso(v.visit_date), 'kind': 'visit', 'type': 'meeting',
                'title': v.purpose or 'Viếng thăm',
                'detail': v.recap_text or v.summary, 'next_action': v.next_action,
                'recording_url': _dl(v.recording_id), 'recap_file_url': _dl(v.recap_file_id),
                'who': v.owner.username if v.owner_id else '',
            })
        for a in (Activity.objects.filter(customer=customer)
                  .select_related('owner', 'recording', 'recap_file')[:50]):
            events.append({
                'date': _iso(a.activity_date), 'kind': 'activity', 'type': a.activity_type,
                'title': a.get_activity_type_display(),
                'detail': a.recap_text or a.content,
                'recording_url': _dl(a.recording_id), 'recap_file_url': _dl(a.recap_file_id),
                'who': a.owner.username if a.owner_id else '',
            })
        for q in Quote.objects.filter(customer=customer).select_related('owner')[:50]:
            events.append({
                'date': _iso(q.created_at), 'kind': 'quote', 'type': q.status,
                'title': f"Báo giá {q.code}", 'status': q.status,
                'amount_vnd': int(q.total_vnd or 0),
                'who': q.owner.username if q.owner_id else '',
            })
        for o in SalesOrder.objects.filter(customer=customer)[:50]:
            events.append({
                'date': _iso(o.issued_date), 'kind': 'order', 'type': o.status,
                'title': f"Đơn hàng {o.code}", 'status': o.status,
                'amount_vnd': int(o.total_vnd or 0), 'who': '',
            })
        for t in Ticket.objects.filter(customer=customer)[:50]:
            events.append({
                'date': _iso(t.created_at), 'kind': 'ticket', 'type': t.status,
                'title': f"Ticket {t.code}: {t.title}", 'status': t.status,
                'detail': t.description, 'who': '',
            })

        events.sort(key=lambda e: e['date'], reverse=True)
        return Response({'results': events[:80], 'count': len(events)})

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _ip(self) -> str | None:
        xff = self.request.META.get('HTTP_X_FORWARDED_FOR')
        return xff.split(',')[0].strip() if xff else self.request.META.get('REMOTE_ADDR')

    def _ua(self) -> str:
        return self.request.META.get('HTTP_USER_AGENT', '')[:200]
