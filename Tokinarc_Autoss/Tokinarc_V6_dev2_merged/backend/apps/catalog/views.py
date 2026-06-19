"""
Tokinarc V6.C-fix2 — apps/catalog/views.py

Read-only endpoint cho Part/Torch.
  GET /api/v1/catalog/parts/                 — list + filter
  GET /api/v1/catalog/parts/search/?q=...    — search (ILIKE name/part_no/aliases)
  GET /api/v1/catalog/parts/{tokin_part_no}/ — detail
  GET /api/v1/catalog/torches/               — list + filter
  GET /api/v1/catalog/torches/{model_code}/  — detail

Permission:
  - List + detail: AllowAny (catalog là public — khách Zalo tra cứu được).
  - Vector search semantic (BGE-M3 + pgvector): TODO khi `seed_embeddings`
    chạy xong; hiện dùng ILIKE để bot hoạt động được ngay.

Triết lý:
  - 100% read-only. Ghi catalog đi qua `seed_from_json` (offline).
  - Pricing đi qua serializer.SerializerMethodField → catalog.pricing
    (vaccine V2 — single source).
"""
from __future__ import annotations

from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, mixins, filters
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.catalog.models import Part, Torch
from apps.catalog.serializers import (
    PartDetailSerializer, PartLiteSerializer,
    TorchDetailSerializer, TorchLiteSerializer,
)


# ─── PartViewSet ─────────────────────────────────────────────────────────────
class PartViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only Part. PK = tokin_part_no (string)."""

    queryset = Part.objects.all().order_by('tokin_part_no')
    permission_classes = [AllowAny]
    lookup_field = 'tokin_part_no'
    lookup_value_regex = r'[^/]+'   # part_no có thể chứa ký tự đặc biệt

    filter_backends   = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields  = ['category', 'ecosystem', 'current_class', 'is_priority_sell']
    search_fields     = ['tokin_part_no', 'display_name_vi', 'display_name_en', 'category']
    ordering_fields   = ['tokin_part_no', 'category', 'price_vnd']

    def get_serializer_class(self):
        return PartDetailSerializer if self.action == 'retrieve' else PartLiteSerializer

    @action(detail=False, methods=['get'])
    def search(self, request):
        """
        Search ILIKE trên display_name_vi/en + tokin_part_no + aliases.
        Params:
          ?q=...           — search term (required, ≥2 ký tự)
          ?top_k=10        — limit (mặc định 10, max 50)
          ?ecosystem=P|D|O — filter optional
          ?category=...    — filter optional
        Trả: {"results": [...], "count": N, "query": "..."}

        Vector search (BGE-M3 + pgvector) — TODO khi embedding seed xong.
        """
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response({'results': [], 'count': 0, 'query': q,
                             'detail': 'Query cần ≥2 ký tự.'})

        try:
            top_k = min(int(request.query_params.get('top_k', 10)), 50)
        except (TypeError, ValueError):
            top_k = 10

        ecosystem = request.query_params.get('ecosystem')
        category  = request.query_params.get('category')

        qs = Part.objects.filter(
            Q(tokin_part_no__icontains=q)
            | Q(display_name_vi__icontains=q)
            | Q(display_name_en__icontains=q)
            | Q(p_part_nos__icontains=q)
            | Q(d_part_nos__icontains=q)
            | Q(o_part_nos__icontains=q)
        )
        if ecosystem:
            qs = qs.filter(ecosystem=ecosystem)
        if category:
            qs = qs.filter(category=category)

        # Priority items first, then by part_no
        qs = qs.order_by('-is_priority_sell', 'tokin_part_no')[:top_k]
        data = PartLiteSerializer(qs, many=True).data
        return Response({'results': data, 'count': len(data), 'query': q})


# ─── TorchViewSet ────────────────────────────────────────────────────────────
class TorchViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only Torch. PK = model_code (string)."""

    queryset = Torch.objects.all().order_by('model_code')
    permission_classes = [AllowAny]
    lookup_field = 'model_code'
    lookup_value_regex = r'[^/]+'

    filter_backends   = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields  = ['family', 'ecosystem', 'current_class', 'cooling', 'is_priority_sell']
    search_fields     = ['model_code', 'display_name_vi', 'display_name_en', 'family']
    ordering_fields   = ['model_code', 'rated_dc_a', 'price_vnd']

    def get_serializer_class(self):
        return TorchDetailSerializer if self.action == 'retrieve' else TorchLiteSerializer

    @action(detail=False, methods=['get'])
    def search(self, request):
        """Search ILIKE trên display_name_vi/en + model_code + family."""
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response({'results': [], 'count': 0, 'query': q,
                             'detail': 'Query cần ≥2 ký tự.'})

        try:
            top_k = min(int(request.query_params.get('top_k', 10)), 50)
        except (TypeError, ValueError):
            top_k = 10

        ecosystem = request.query_params.get('ecosystem')

        qs = Torch.objects.filter(
            Q(model_code__icontains=q)
            | Q(display_name_vi__icontains=q)
            | Q(display_name_en__icontains=q)
            | Q(family__icontains=q)
        )
        if ecosystem:
            qs = qs.filter(ecosystem=ecosystem)

        qs = qs.order_by('-is_priority_sell', 'model_code')[:top_k]
        data = TorchLiteSerializer(qs, many=True).data
        return Response({'results': data, 'count': len(data), 'query': q})
