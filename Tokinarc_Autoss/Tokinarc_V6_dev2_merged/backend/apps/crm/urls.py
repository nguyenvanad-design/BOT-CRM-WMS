"""
Tokinarc V6.C — apps/crm/urls.py

Include vào tokinarc/urls.py:
    path('api/v1/crm/', include('apps.crm.urls')),
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .contacts import ContactViewSet
from .contracts_activities import ActivityViewSet, ContractViewSet
from .imports import CustomerImportTemplateView, CustomerImportView
from .receivables import ReceivablesView
from .views import CustomerViewSet
from .views_ext import (
    LeadViewSet, OpportunityViewSet, QuoteViewSet, TicketViewSet, VisitViewSet,
)

router = DefaultRouter()
router.register(r'customers', CustomerViewSet, basename='customer')
router.register(r'contacts', ContactViewSet, basename='contact')
router.register(r'leads', LeadViewSet, basename='lead')
router.register(r'opportunities', OpportunityViewSet, basename='opportunity')
router.register(r'quotes', QuoteViewSet, basename='quote')
router.register(r'visits', VisitViewSet, basename='visit')
router.register(r'tickets', TicketViewSet, basename='ticket')
router.register(r'contracts', ContractViewSet, basename='contract')
router.register(r'activities', ActivityViewSet, basename='activity')

# Đặt TRƯỚC router để 'customers/import/' không bị nuốt bởi 'customers/<pk>/'.
urlpatterns = [
    path('customers/import/', CustomerImportView.as_view(), name='customer-import'),
    path('customers/import-template/', CustomerImportTemplateView.as_view(),
         name='customer-import-template'),
] + router.urls + [
    path('receivables/', ReceivablesView.as_view(), name='receivables'),
]
