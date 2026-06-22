"""
Tokinarc V6.C — apps/sales/views.py — khớp V6.B.3 §3.4
"""
from __future__ import annotations

from django.db.models import F, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.models import AuditLog

from . import services
from .models import Payment, SalesOrder
from .permissions import SalesPermission, role_of
from .serializers import (
    PaymentSerializer, SalesOrderDetailSerializer, SalesOrderListSerializer,
)


def _publish(channel, payload):
    try:
        from tokinarc.eventbus.publisher import publish
        publish(channel, payload)
    except Exception:
        pass


def _create_outbound_for_order(order, user) -> str | None:
    """Khi ship đơn → tự tạo WMS OutboundOrder (draft) gắn sales_order_code.
    Trả mã phiếu xuất, hoặc None nếu không có kho mặc định / đã có phiếu."""
    from apps.catalog.models import Part
    from apps.wms.models import OutboundLine, OutboundOrder, Warehouse

    if OutboundOrder.objects.filter(sales_order_code=order.code).exists():
        return None
    actives = Warehouse.objects.filter(is_active=True)
    wh = actives.first() if actives.count() == 1 else actives.filter(is_default=True).first()
    if wh is None:
        return None
    year = timezone.now().year
    pre = f'OUT-{year}-'
    last = OutboundOrder.objects.filter(code__startswith=pre).order_by('-code').first()
    seq = (int(last.code.rsplit('-', 1)[-1]) + 1) if last else 1
    code = f'{pre}{seq:03d}'
    ob = OutboundOrder.objects.create(
        code=code, warehouse=wh, sales_order_code=order.code, customer=order.customer,
        created_by=user, updated_by=user,
    )
    for idx, ol in enumerate(order.lines.all()):
        if ol.part_id:
            OutboundLine.objects.create(
                outbound=ob, part=Part.objects.filter(pk=ol.part_id).first(),
                qty_ordered=ol.qty, order_idx=idx)
    return code


class SalesOrderViewSet(viewsets.ModelViewSet):
    permission_classes = [SalesPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'order_type', 'customer', 'owner']
    search_fields = ['code', 'customer__name']
    ordering_fields = ['issued_date', 'total_vnd', 'created_at']

    def get_queryset(self):
        qs = (SalesOrder.objects.select_related('customer', 'owner')
              .prefetch_related('lines')
              .annotate(debt_vnd=F('total_vnd') - F('paid_vnd')))
        if role_of(self.request.user) not in ('manager', 'admin'):
            qs = qs.filter(owner_id=self.request.user.id)
        return qs

    def get_serializer_class(self):
        return SalesOrderListSerializer if self.action == 'list' else SalesOrderDetailSerializer

    def perform_create(self, serializer):
        owner = serializer.validated_data.get('owner') or self.request.user
        if role_of(self.request.user) not in ('manager', 'admin'):
            owner = self.request.user
        order = serializer.save(owner=owner, created_by=self.request.user,
                                updated_by=self.request.user)
        AuditLog.record(user=self.request.user, action='create', entity='sales.SalesOrder',
                        entity_id=order.id, diff={'code': order.code})

    @action(detail=True, methods=['post'])
    def sign(self, request, pk=None):
        order = self.get_object()
        if order.status not in ('draft', 'pending'):
            return Response({'detail': 'Chỉ ký được đơn nháp/chờ ký.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        order.status = 'active'
        order.save(update_fields=['status'])
        AuditLog.record(user=request.user, action='sign', entity='sales.SalesOrder',
                        entity_id=order.id)
        return Response(SalesOrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'])
    def ship(self, request, pk=None):
        order = self.get_object()
        if order.status != 'active':
            return Response({'detail': 'Đơn chưa hiệu lực.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        order.status = 'shipping'
        order.save(update_fields=['status'])
        outbound_code = _create_outbound_for_order(order, request.user)
        from tokinarc.eventbus.channels import Channel
        _publish(Channel.ORDER_SHIPPED, {'order': order.code, 'customer_id': str(order.customer_id),
                                         'outbound': outbound_code})
        data = SalesOrderDetailSerializer(order).data
        data['outbound_code'] = outbound_code
        return Response(data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        if order.status in ('completed', 'cancelled'):
            return Response({'detail': 'Không thể hủy.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        order.status = 'cancelled'
        order.save(update_fields=['status'])
        return Response(SalesOrderDetailSerializer(order).data)

    @action(detail=False, methods=['get'], url_path='debt-aging')
    def debt_aging(self, request):
        qs = (self.get_queryset()
              .filter(status__in=['active', 'shipping', 'completed'], total_vnd__gt=F('paid_vnd')))
        data = [{'code': o.code, 'customer': o.customer.name,
                 'amount_due': o.total_vnd - o.paid_vnd,
                 'issued_date': o.issued_date} for o in qs]
        return Response({'count': len(data), 'results': data})

    @action(detail=False, methods=['get'])
    def summary(self, request):
        qs = self.get_queryset()
        agg = qs.aggregate(total=Sum('total_vnd'), paid=Sum('paid_vnd'))
        total = agg['total'] or 0
        paid = agg['paid'] or 0
        return Response({'total_vnd': total, 'paid_vnd': paid, 'debt_vnd': total - paid,
                         'order_count': qs.count()})


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.select_related('order')
    serializer_class = PaymentSerializer
    permission_classes = [SalesPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['order', 'method']

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = ser.validated_data['order']
        try:
            p = services.record_payment(
                order, amount=ser.validated_data['amount_vnd'],
                paid_at=ser.validated_data['paid_at'],
                method=ser.validated_data['method'],
                reference=ser.validated_data.get('reference', ''), user=request.user)
        except ValueError as e:
            return Response({'detail': str(e), 'code': 'VALIDATION_FAILED'},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(PaymentSerializer(p).data, status=status.HTTP_201_CREATED)
