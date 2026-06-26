"""
Tokinarc V6.C — apps/analytics/views.py — khớp V6.B.3 §3.6 (chỉ đọc, manager+)
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import INTERNAL_ROLES, MANAGER_ROLES

from . import assistant, services


class IsManagerOrAdmin(BasePermission):
    message = "Chỉ quản lý/CEO/admin xem được dashboard CEO."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and getattr(u, 'role', '') in MANAGER_ROLES)


class IsInternalStaff(BasePermission):
    """Bot nội bộ: mọi nhân viên (role != customer). Khách KHÔNG vào được."""
    message = "Chỉ nhân viên nội bộ dùng được trợ lý này."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and getattr(u, 'role', '') in INTERNAL_ROLES)


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


class PayableView(_Base):
    """Công nợ phải TRẢ NCC (manager+) → tổng + theo nhà cung cấp."""
    def get(self, request):
        return Response(services.payable_summary())


class InventoryValueView(_Base):
    def get(self, request):
        return Response(services.inventory_value(request.query_params.get('warehouse')))


class PipelineForecastView(_Base):
    def get(self, request):
        return Response(services.pipeline_forecast())


class AssistantQueryView(APIView):
    """Trợ lý NỘI BỘ (mọi nhân viên; mỗi intent tự gate role bên trong).
    POST {query} → {text}. Có thể tạo báo giá/hợp đồng/phiếu kho theo quyền."""
    permission_classes = [IsInternalStaff]

    def post(self, request):
        q = (request.data.get('query') or '').strip()
        up = request.FILES.get('file')
        if up is not None:
            data = up.read()
            if len(data) > 15 * 1024 * 1024:
                return Response({'detail': 'File quá lớn (tối đa 15MB).'}, status=400)
            text = assistant.analyze_attachment(q, data, up.content_type or '', up.name or '')
            return Response({'text': text, 'mode': 'attachment', 'success': True})
        if not q:
            return Response({'detail': 'Thiếu câu hỏi.'}, status=400)
        return Response({'text': assistant.answer(q, request.user), 'success': True})


class AssistantSummaryView(_Base):
    """Tóm tắt điều hành toàn phòng ban (manager+). GET → {summary, metrics, generated_by}."""
    def get(self, request):
        return Response(assistant.executive_summary())


class SummaryExportView(_Base):
    """Xuất báo cáo điều hành ra Excel (manager+). GET → file .xlsx."""
    def get(self, request):
        import io
        from datetime import date

        from django.http import HttpResponse
        from openpyxl import Workbook

        data = assistant.executive_summary()
        m = data['metrics']
        wb = Workbook(); ws = wb.active; ws.title = 'BaoCaoDieuHanh'
        ws.append(['Báo cáo điều hành Tokinarc', date.today().isoformat()])
        ws.append([])
        labels = {
            'revenue_month': 'Doanh thu tháng (₫)', 'collected_month': 'Đã thu tháng (₫)',
            'debt_total': 'Công nợ phải thu (₫)', 'overdue': 'Quá hạn (₫)',
            'pipeline_weighted': 'Pipeline weighted (₫)', 'customers': 'Số khách hàng',
            'dormant_customers': 'KH chưa mua >3 tháng', 'open_leads': 'Lead đang mở',
            'open_opportunities': 'Cơ hội đang mở', 'open_tickets': 'Ticket đang mở',
            'urgent_tickets': 'Ticket khẩn', 'inventory_value': 'Giá trị tồn kho (₫)',
            'sku_count': 'Số SKU', 'low_stock': 'Mặt hàng sắp hết',
            'top_customer': 'KH lớn nhất', 'top_customer_revenue': 'Doanh số KH lớn nhất (₫)',
        }
        ws.append(['Chỉ số', 'Giá trị'])
        for k, lbl in labels.items():
            ws.append([lbl, m.get(k)])
        ws.append([])
        ws.append(['Tóm tắt'])
        for line in (data['summary'] or '').split('\n'):
            ws.append([line])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        resp = HttpResponse(
            buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="bao_cao_dieu_hanh_{date.today().isoformat()}.xlsx"'
        return resp


class SalesPerformanceView(APIView):
    """Hiệu suất theo từng SALE (chỉ quản lý+). Một dòng/nhân viên: KH, lead,
    cơ hội mở, pipeline, weighted, won, đơn, doanh thu, đã thu."""
    permission_classes = [IsManagerOrAdmin]

    OPEN_OPP = ['prospect', 'qualify', 'proposal', 'negotiate']
    ACTIVE_LEAD = ['new', 'contacted', 'qualified']
    REVENUE_ORDER = ['active', 'shipping', 'completed']

    def get(self, request):
        from django.contrib.auth import get_user_model
        from django.db.models import Count, Sum

        from apps.crm.models import Customer, Lead, Opportunity
        from apps.sales.models import SalesOrder

        User = get_user_model()
        sellers = User.objects.filter(role__in=['sales', 'manager'], is_active=True).order_by('username')
        rows = {u.id: {'id': str(u.id), 'username': u.username, 'name': u.display_name or u.username,
                       'customers': 0, 'leads': 0, 'open_opps': 0, 'pipeline_vnd': 0,
                       'weighted_vnd': 0, 'won_opps': 0, 'orders': 0,
                       'revenue_vnd': 0, 'collected_vnd': 0} for u in sellers}

        for r in Customer.objects.filter(deleted_at__isnull=True).values('owner').annotate(c=Count('id')):
            if r['owner'] in rows:
                rows[r['owner']]['customers'] = int(r['c'] or 0)
        for r in Lead.objects.filter(status__in=self.ACTIVE_LEAD).values('owner').annotate(c=Count('id')):
            if r['owner'] in rows:
                rows[r['owner']]['leads'] = int(r['c'] or 0)
        for o in Opportunity.objects.filter(stage__in=self.OPEN_OPP).values('owner', 'est_value_vnd', 'probability'):
            r = rows.get(o['owner'])
            if r:
                val = int(o['est_value_vnd'] or 0)
                r['open_opps'] += 1
                r['pipeline_vnd'] += val
                r['weighted_vnd'] += val * int(o['probability'] or 0) // 100
        for r in Opportunity.objects.filter(stage='won').values('owner').annotate(c=Count('id')):
            if r['owner'] in rows:
                rows[r['owner']]['won_opps'] = int(r['c'] or 0)
        for r in (SalesOrder.objects.filter(status__in=self.REVENUE_ORDER, deleted_at__isnull=True)
                  .values('owner').annotate(c=Count('id'), rev=Sum('total_vnd'), col=Sum('paid_vnd'))):
            if r['owner'] in rows:
                rows[r['owner']]['orders'] = int(r['c'] or 0)
                rows[r['owner']]['revenue_vnd'] = int(r['rev'] or 0)
                rows[r['owner']]['collected_vnd'] = int(r['col'] or 0)

        return Response(sorted(rows.values(), key=lambda x: -x['revenue_vnd']))
