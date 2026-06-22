"""
Tokinarc V6.C — apps/crm/activity_feed.py

Nhật ký hoạt động của sale: gộp Visit + Activity + Lead + Báo giá + Đơn + Ticket
của 1 người, sắp theo thời gian (giảm dần). FE nhóm theo ngày.

  GET /api/v1/crm/my-activity/?days=7&owner=<id>
    - Sale       → chỉ việc của mình (bỏ qua ?owner).
    - Manager+   → mặc định cả team; lọc 1 người qua ?owner=<user_id>.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import is_manager

from .models import Activity, Lead, Quote, Ticket, Visit


class MyActivityFeedView(APIView):
    """Dòng thời gian việc-đã-làm của 1 sale (mọi loại, mọi khách)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            days = int(request.query_params.get('days', 7))
        except (TypeError, ValueError):
            days = 7
        days = max(1, min(days, 90))
        since = timezone.now() - timedelta(days=days)
        since_date = since.date()

        u = request.user
        target = request.query_params.get('owner') if is_manager(u) else str(u.id)

        def own(qs, field='owner_id'):
            return qs.filter(**{field: target}) if target else qs

        def who(obj, field='owner'):
            o = getattr(obj, field, None)
            return o.username if o else ''

        events: list[dict] = []

        for v in own(Visit.objects.filter(visit_date__gte=since_date)
                     .select_related('owner', 'customer'))[:200]:
            events.append({
                'date': v.visit_date.isoformat(), 'kind': 'visit',
                'title': v.purpose or 'Viếng thăm khách',
                'customer': v.customer.name if v.customer_id else '',
                'detail': v.recap_text or v.summary, 'who': who(v), 'link': '/visits',
            })
        for a in own(Activity.objects.filter(activity_date__gte=since)
                     .select_related('owner', 'customer'))[:200]:
            events.append({
                'date': a.activity_date.isoformat(), 'kind': 'activity',
                'title': a.get_activity_type_display(),
                'customer': a.customer.name if a.customer_id else '',
                'detail': a.recap_text or a.content, 'who': who(a), 'link': '/activities',
            })
        for l in own(Lead.objects.filter(created_at__gte=since)
                     .select_related('owner'))[:200]:
            events.append({
                'date': l.created_at.isoformat(), 'kind': 'lead',
                'title': f'Lead mới: {l.name}', 'customer': l.company,
                'detail': l.phone, 'who': who(l), 'link': '/leads',
            })
        for q in own(Quote.objects.filter(created_at__gte=since)
                     .select_related('owner', 'customer'))[:200]:
            events.append({
                'date': q.created_at.isoformat(), 'kind': 'quote',
                'title': f'Báo giá {q.code}',
                'customer': q.customer.name if q.customer_id else '',
                'amount_vnd': int(q.total_vnd or 0), 'status': q.status,
                'who': who(q), 'link': '/quotes',
            })
        for t in own(Ticket.objects.filter(created_at__gte=since)
                     .select_related('created_owner', 'customer'), field='created_owner_id')[:200]:
            events.append({
                'date': t.created_at.isoformat(), 'kind': 'ticket',
                'title': f'Ticket {t.code}: {t.title}',
                'customer': t.customer.name if t.customer_id else '',
                'status': t.status, 'who': who(t, 'created_owner'), 'link': '/tickets',
            })

        # Đơn bán (sales app) — import muộn tránh vòng phụ thuộc.
        from apps.sales.models import SalesOrder
        for o in own(SalesOrder.objects.filter(created_at__gte=since)
                     .select_related('owner', 'customer'))[:200]:
            events.append({
                'date': o.created_at.isoformat(), 'kind': 'order',
                'title': f'Đơn bán {o.code}',
                'customer': o.customer.name if o.customer_id else '',
                'amount_vnd': int(o.total_vnd or 0), 'status': o.status,
                'who': who(o), 'link': '/orders',
            })

        events.sort(key=lambda e: e['date'], reverse=True)
        return Response({'count': len(events), 'days': days, 'results': events})
