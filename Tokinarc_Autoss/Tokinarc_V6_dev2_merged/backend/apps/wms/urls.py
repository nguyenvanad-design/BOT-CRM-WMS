"""
Tokinarc V6.C — apps/wms/urls.py

Include vào tokinarc/urls.py:
    path('api/v1/wms/', include('apps.wms.urls')),
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ASNViewSet, BinViewSet, CycleCountViewSet, InboundViewSet, InventoryViewSet,
    LotViewSet, OpsKpiView, OutboundViewSet, SerialNumberViewSet,
    StockMovementViewSet, WarehouseViewSet, ZoneViewSet,
)

router = DefaultRouter()
router.register(r'warehouses', WarehouseViewSet, basename='warehouse')
router.register(r'zones', ZoneViewSet, basename='zone')
router.register(r'bins', BinViewSet, basename='bin')
router.register(r'inventory', InventoryViewSet, basename='inventory')
router.register(r'serials', SerialNumberViewSet, basename='serial')
router.register(r'lots', LotViewSet, basename='lot')
router.register(r'stock-movements', StockMovementViewSet, basename='stockmovement')
router.register(r'asn', ASNViewSet, basename='asn')
router.register(r'inbound', InboundViewSet, basename='inbound')
router.register(r'outbound', OutboundViewSet, basename='outbound')
router.register(r'cycle-counts', CycleCountViewSet, basename='cyclecount')

urlpatterns = router.urls + [
    path('ops-kpi/', OpsKpiView.as_view(), name='wms-ops-kpi'),
]
