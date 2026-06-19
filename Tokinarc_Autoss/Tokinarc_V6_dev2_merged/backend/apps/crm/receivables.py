"""
Tokinarc V6 — apps/crm/receivables.py

Công nợ phải thu cho CRM (theo dõi thu hồi). Khác debt-aging của analytics
(CEO, manager-only): endpoint này TÔN TRỌNG OWNERSHIP —
  - sale: chỉ thấy công nợ của KH mình phụ trách,
  - manager/admin: thấy toàn bộ.

GET /api/v1/crm/receivables/  →  { summary, results }
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import F
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import is_manager

from .permissions import IsAuthenticatedWithRole

_ACTIVE = ['active', 'shipping', 'completed']


def _due_date(order) -> date:
    if order.payment_terms == 'net_30':
        return order.issued_date + timedelta(days=30)
    if order.payment_terms == 'net_60':
        return order.issued_date + timedelta(days=60)
    return order.issued_date


def _bucket(overdue: int) -> str:
    if overdue == 0:
        return 'current'
    if overdue <= 30:
        return 'd1_30'
    if overdue <= 60:
        return 'd31_60'
    return 'd60p'


class ReceivablesView(APIView):
    """Danh sách công nợ + phân tích tuổi nợ, lọc theo quyền sở hữu KH."""
    permission_classes = [IsAuthenticatedWithRole]

    def get(self, request):
        from apps.sales.models import SalesOrder

        u = request.user
        qs = (SalesOrder.objects
              .filter(status__in=_ACTIVE, total_vnd__gt=F('paid_vnd'))
              .select_related('customer'))
        if not is_manager(u):
            qs = qs.filter(customer__owner_id=u.id)

        today = date.today()
        buckets = {'current': 0, 'd1_30': 0, 'd31_60': 0, 'd60p': 0}
        total = 0
        results = []
        for o in qs:
            overdue = max(0, (today - _due_date(o)).days)
            amount = int(o.total_vnd - o.paid_vnd)
            b = _bucket(overdue)
            buckets[b] += amount
            total += amount
            results.append({
                'code':         o.code,
                'customer':     o.customer.name,
                'customer_id':  str(o.customer.id),
                'amount_due':   amount,
                'days_overdue': overdue,
                'bucket':       b,
                'issued_date':  str(o.issued_date),
            })
        results.sort(key=lambda r: r['days_overdue'], reverse=True)

        return Response({
            'summary': {
                'total_due': total,
                'count':     len(results),
                'overdue':   buckets['d1_30'] + buckets['d31_60'] + buckets['d60p'],
                **buckets,
            },
            'results': results,
        })
