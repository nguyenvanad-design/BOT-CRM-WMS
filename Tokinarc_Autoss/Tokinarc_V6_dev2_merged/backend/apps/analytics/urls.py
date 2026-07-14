"""Tokinarc V6.C — apps/analytics/urls.py"""
from django.urls import path
from .views import (KpiOverviewView, RevenueMonthlyView, RevenueBySegmentView,
                    DebtAgingView, PayableView, InventoryValueView, PipelineForecastView,
                    InventoryAgingView, DeadStockView,
                    AssistantQueryView, AssistantSummaryView, SummaryExportView,
                    SalesPerformanceView,
                    RevenueSummaryView, CustomerDebtView,
                    TopCustomersView, DormantCustomersView, ReorderSuggestionView,
                    SlowMovingView, ExecutiveMetricsView)
urlpatterns = [
    path('sales-performance/', SalesPerformanceView.as_view()),
    path('kpi/overview/', KpiOverviewView.as_view()),
    path('revenue/monthly/', RevenueMonthlyView.as_view()),
    path('revenue/by-segment/', RevenueBySegmentView.as_view()),
    path('debt-aging/', DebtAgingView.as_view()),
    path('payable/', PayableView.as_view()),
    path('inventory/value/', InventoryValueView.as_view()),
    path('inventory/aging/', InventoryAgingView.as_view()),
    path('inventory/dead-stock/', DeadStockView.as_view()),
    path('forecast/pipeline/', PipelineForecastView.as_view()),
    # Bot nội bộ (đọc qua API): doanh thu kỳ, công nợ, top KH, KH ngủ đông, đề nghị nhập, hàng chậm, điều hành.
    path('revenue-summary/', RevenueSummaryView.as_view()),
    path('customer-debt/', CustomerDebtView.as_view()),
    path('top-customers/', TopCustomersView.as_view()),
    path('dormant-customers/', DormantCustomersView.as_view()),
    path('reorder-suggestions/', ReorderSuggestionView.as_view()),
    path('slow-moving/', SlowMovingView.as_view()),
    path('executive-metrics/', ExecutiveMetricsView.as_view()),
    path('assistant/query/', AssistantQueryView.as_view()),
    path('assistant/summary/', AssistantSummaryView.as_view()),
    path('assistant/summary/export/', SummaryExportView.as_view()),
]
