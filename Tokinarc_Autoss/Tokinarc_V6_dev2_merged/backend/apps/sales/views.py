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

from apps.accounts.roles import is_manager
from apps.common.models import AuditLog

from . import services
from .models import Invoice, Payment, SalesOrder
from .permissions import SalesPermission, role_of  # noqa: F401 (role_of dùng nơi khác)
from .serializers import (
    InvoiceSerializer, PaymentSerializer, SalesOrderDetailSerializer,
    SalesOrderListSerializer,
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
        if not is_manager(self.request.user):
            qs = qs.filter(owner_id=self.request.user.id)
        return qs

    def get_serializer_class(self):
        return SalesOrderListSerializer if self.action == 'list' else SalesOrderDetailSerializer

    def perform_create(self, serializer):
        owner = serializer.validated_data.get('owner') or self.request.user
        if not is_manager(self.request.user):
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

    @action(detail=True, methods=['post'], url_path='create-invoice')
    def create_invoice(self, request, pk=None):
        """Xuất hóa đơn VAT từ đơn bán. Body tùy chọn {tax_pct} (mặc định 8%)."""
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý/CEO/admin xuất hóa đơn.'}, status=403)
        order = self.get_object()
        if order.status in ('draft', 'cancelled'):
            return Response({'detail': 'Đơn chưa hiệu lực, không xuất hóa đơn.', 'code': 'CONFLICT'},
                            status=status.HTTP_409_CONFLICT)
        from decimal import Decimal
        try:
            tax_pct = Decimal(str(request.data.get('tax_pct', 8)))
        except Exception:  # noqa: BLE001
            tax_pct = Decimal('8')
        year = timezone.now().year
        pre = f'INV-{year}-'
        last = Invoice.objects.filter(code__startswith=pre).order_by('-code').first()
        seq = (int(last.code.rsplit('-', 1)[-1]) + 1) if last else 1
        subtotal = order.total_vnd or 0
        tax = (subtotal * tax_pct / 100).quantize(Decimal('1'))
        inv = Invoice.objects.create(
            code=f'{pre}{seq:03d}', order=order, customer=order.customer,
            issue_date=timezone.now().date(), subtotal_vnd=subtotal, tax_pct=tax_pct,
            tax_vnd=tax, total_vnd=subtotal + tax, created_by=request.user, updated_by=request.user)
        AuditLog.record(user=request.user, action='create', entity='sales.Invoice',
                        entity_id=inv.id, diff={'code': inv.code})
        return Response(InvoiceSerializer(inv).data, status=201)

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


class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """Hóa đơn (đọc). Tạo qua /orders/{id}/create-invoice/."""
    serializer_class = InvoiceSerializer
    permission_classes = [SalesPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['order', 'customer', 'status']

    def get_queryset(self):
        qs = Invoice.objects.select_related('order', 'customer')
        if not is_manager(self.request.user):
            qs = qs.filter(order__owner_id=self.request.user.id)
        return qs
