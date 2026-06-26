"""Tokinarc V6.C — apps/analytics/urls.py"""
from django.urls import path
from .views import (KpiOverviewView, RevenueMonthlyView, RevenueBySegmentView,
                    DebtAgingView, PayableView, InventoryValueView, PipelineForecastView,
                    AssistantQueryView, AssistantSummaryView, SummaryExportView,
                    SalesPerformanceView)
urlpatterns = [
    path('sales-performance/', SalesPerformanceView.as_view()),
    path('kpi/overview/', KpiOverviewView.as_view()),
    path('revenue/monthly/', RevenueMonthlyView.as_view()),
    path('revenue/by-segment/', RevenueBySegmentView.as_view()),
    path('debt-aging/', DebtAgingView.as_view()),
    path('payable/', PayableView.as_view()),
    path('inventory/value/', InventoryValueView.as_view()),
    path('forecast/pipeline/', PipelineForecastView.as_view()),
    path('assistant/query/', AssistantQueryView.as_view()),
    path('assistant/summary/', AssistantSummaryView.as_view()),
    path('assistant/summary/export/', SummaryExportView.as_view()),
]
