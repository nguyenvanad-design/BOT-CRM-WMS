"""
Tokinarc V6.C — apps/analytics/views.py — khớp V6.B.3 §3.6 (chỉ đọc, manager+)
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import MANAGER_ROLES

from . import assistant, services


class IsManagerOrAdmin(BasePermission):
    message = "Chỉ quản lý/CEO/admin xem được dashboard CEO."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and getattr(u, 'role', '') in MANAGER_ROLES)


class _Base(APIView):
    permission_classes = [IsManagerOrAdmin]


class KpiOverviewView(_Base):
    def get(self, request):
        return Response(services.kpi_overview())


class RevenueMonthlyView(_Base):
    def get(self, request):
        year = request.query_params.get('year')
        return Response(services.revenue_monthly(int(year) if year else None))


class RevenueBySegmentView(_Base):
    def get(self, request):
        return Response(services.revenue_by_segment())


class DebtAgingView(_Base):
    def get(self, request):
        data = services.debt_aging()
        return Response({'count': len(data), 'results': data})


class InventoryValueView(_Base):
    def get(self, request):
        return Response(services.inventory_value(request.query_params.get('warehouse')))


class PipelineForecastView(_Base):
    def get(self, request):
        return Response(services.pipeline_forecast())


class AssistantQueryView(_Base):
    """Trợ lý CRM nội bộ (manager+). POST {query} → {text}."""
    def post(self, request):
        q = (request.data.get('query') or '').strip()
        if not q:
            return Response({'detail': 'Thiếu câu hỏi.'}, status=400)
        return Response({'text': assistant.answer(q), 'success': True})


class AssistantSummaryView(_Base):
    """Tóm tắt điều hành toàn phòng ban (manager+). GET → {summary, metrics, generated_by}."""
    def get(self, request):
        return Response(assistant.executive_summary())
