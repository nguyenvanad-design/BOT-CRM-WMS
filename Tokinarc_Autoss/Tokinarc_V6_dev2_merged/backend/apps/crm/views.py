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

        payload = {
            'customer':      customer,
            'open_orders':   open_orders,
            'debt_vnd':      debt_vnd,
            'open_tickets':  open_tickets,
            'last_activity': last_activity,
        }
        ser = Customer360Serializer(payload)
        return Response(ser.data)

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _ip(self) -> str | None:
        xff = self.request.META.get('HTTP_X_FORWARDED_FOR')
        return xff.split(',')[0].strip() if xff else self.request.META.get('REMOTE_ADDR')

    def _ua(self) -> str:
        return self.request.META.get('HTTP_USER_AGENT', '')[:200]
