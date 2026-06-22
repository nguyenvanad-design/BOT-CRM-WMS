"""
Tokinarc V6.C — apps/crm/lead_report.py

Báo cáo Lead theo NGUỒN (và chiến dịch): số lead, số đã chuyển thành KH, tỉ lệ.
  GET /api/v1/crm/lead-sources/?days=
    - Sale     → chỉ lead của mình.
    - Manager+ → toàn bộ.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import is_manager

from .models import Lead, LeadSource


class LeadSourceReportView(APIView):
    """Thống kê lead theo nguồn + chiến dịch."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            days = int(request.query_params.get('days', 90))
        except (TypeError, ValueError):
            days = 90
        days = max(1, min(days, 365))
        since = timezone.now() - timedelta(days=days)

        qs = Lead.objects.filter(created_at__gte=since)
        if not is_manager(request.user):
            qs = qs.filter(owner_id=request.user.id)

        labels = dict(LeadSource.choices)
        agg = (qs.values('source')
               .annotate(total=Count('id'),
                         converted=Count('id', filter=Q(status='converted')))
               .order_by('-total'))
        by_source = []
        for row in agg:
            src = row['source'] or 'other'
            total, conv = row['total'], row['converted']
            by_source.append({
                'source': src,
                'source_label': labels.get(src, src or 'Khác'),
                'total': total,
                'converted': conv,
                'conversion_pct': round(conv * 100 / total, 1) if total else 0.0,
            })

        camp = (qs.exclude(campaign='')
                .values('campaign', 'source')
                .annotate(total=Count('id'),
                          converted=Count('id', filter=Q(status='converted')))
                .order_by('-total')[:50])
        by_campaign = [{
            'campaign': r['campaign'],
            'source_label': labels.get(r['source'], r['source'] or 'Khác'),
            'total': r['total'], 'converted': r['converted'],
            'conversion_pct': round(r['converted'] * 100 / r['total'], 1) if r['total'] else 0.0,
        } for r in camp]

        total_leads = qs.count()
        total_conv = qs.filter(status='converted').count()
        return Response({
            'days': days,
            'summary': {
                'total': total_leads, 'converted': total_conv,
                'conversion_pct': round(total_conv * 100 / total_leads, 1) if total_leads else 0.0,
            },
            'by_source': by_source,
            'by_campaign': by_campaign,
        })
