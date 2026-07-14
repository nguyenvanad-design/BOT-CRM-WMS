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
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from rest_framework import serializers as drf_serializers

from apps.catalog.models import Part, Torch, ProcedureQA
from apps.catalog.serializers import (
    PartDetailSerializer, PartLiteSerializer,
    TorchDetailSerializer, TorchLiteSerializer,
)


# ─── ProcedureQA — tra cứu lắp đặt / sửa chữa (nội bộ) ────────────────────────
class ProcedureSerializer(drf_serializers.ModelSerializer):
    intent_display = drf_serializers.CharField(source='get_intent_display', read_only=True)

    class Meta:
        model = ProcedureQA
        fields = ['id', 'intent', 'intent_display', 'question', 'answer', 'source']


class ProcedureViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Tra cứu Q&A lắp đặt/sửa chữa cho nhân sự nội bộ. ?q=... &intent=INSTALLATION|REPAIR|LOOKUP"""
    serializer_class = ProcedureSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ProcedureQA.objects.all()
        intent = (self.request.query_params.get('intent') or '').upper()
        q = self.request.query_params.get('q') or self.request.query_params.get('search')
        if intent in ('INSTALLATION', 'REPAIR', 'LOOKUP'):
            qs = qs.filter(intent=intent)
        if q:
            # OR theo từng token (bot nội bộ truyền chuỗi token đã lọc stopword) → recall tốt hơn.
            toks = [t for t in q.split() if len(t) >= 2] or [q]
            cond = Q()
            for t in toks:
                cond |= Q(question__icontains=t) | Q(answer__icontains=t)
            qs = qs.filter(cond)
        return qs


# ─── PartViewSet ─────────────────────────────────────────────────────────────
class PartViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only Part. PK = tokin_part_no (string)."""

    queryset = Part.objects.all().order_by('tokin_part_no')
    permission_classes = [AllowAny]
    lookup_field = 'tokin_part_no'
    lookup_value_regex = r'[^/]+'   # part_no có thể chứa ký tự đặc biệt

    filter_backends   = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields  = ['category', 'ecosystem', 'current_class', 'is_priority_sell']
    search_fields     = ['tokin_part_no', 'display_name_vi', 'display_name_en', 'category', 'barcode']
    ordering_fields   = ['tokin_part_no', 'category', 'price_vnd']

    def get_serializer_class(self):
        return PartDetailSerializer if self.action == 'retrieve' else PartLiteSerializer

    @action(detail=True, methods=['get', 'patch'], permission_classes=[IsAuthenticated])
    def cost(self, request, tokin_part_no=None):
        """Giá vốn (NHẠY CẢM — chỉ manager+). GET: xem vốn + lãi gộp. PATCH: chỉnh vốn."""
        from apps.accounts.roles import is_manager
        from apps.catalog.pricing import get_effective_price
        if not is_manager(request.user):
            return Response({'detail': 'Chỉ quản lý/CEO/admin được xem/sửa giá vốn.'}, status=403)
        part = self.get_object()
        if request.method == 'PATCH':
            raw = request.data.get('cost_vnd')
            try:
                part.cost_vnd = int(raw) if raw not in (None, '') else None
            except (TypeError, ValueError):
                return Response({'detail': 'Giá vốn không hợp lệ.'}, status=400)
            part.save(update_fields=['cost_vnd'])
        sell = int(get_effective_price(part) or 0)
        cost = int(part.cost_vnd or 0)
        margin = sell - cost
        return Response({
            'part_no': part.pk, 'name': part.display_name_vi,
            'cost_vnd': cost or None, 'price_vnd': sell,
            'margin_vnd': margin if cost else None,
            'margin_pct': round(margin / sell * 100, 1) if (sell and cost) else None,
        })

    @action(detail=True, methods=['post'], url_path='set-barcode', permission_classes=[IsAuthenticated])
    def set_barcode(self, request, tokin_part_no=None):
        """Quét-gán: gán barcode/QR (EAN, mã Tokin) trên tem cho part này → lần sau quét ra ngay.
        Chỉ nhân viên nội bộ. Nếu mã đã gán cho part KHÁC → báo lỗi (tránh trùng)."""
        from apps.accounts.roles import Role, role_of
        if role_of(request.user) == Role.CUSTOMER:
            return Response({'detail': 'Chỉ nhân viên nội bộ được gán mã.'}, status=403)
        code = (request.data.get('barcode') or '').strip()
        if not code:
            return Response({'detail': 'Thiếu mã barcode.'}, status=400)
        clash = Part.objects.filter(barcode=code).exclude(pk=tokin_part_no).first()
        if clash is not None:
            return Response({'detail': f'Mã "{code}" đã gán cho {clash.pk} ({clash.display_name_vi}).',
                             'code': 'BARCODE_TAKEN'}, status=409)
        part = self.get_object()
        part.barcode = code
        part.save(update_fields=['barcode'])
        return Response({'part_no': part.pk, 'name': part.display_name_vi, 'barcode': code})

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def compatibility(self, request):
        """Đồ đi kèm/tương thích với 1 mã (nội bộ). ?part=001002 → danh sách to_part + bắt buộc."""
        from apps.catalog.models import CompatibilityEdge
        pn = (request.query_params.get('part') or '').strip()
        if not pn:
            return Response({'part': '', 'results': []})
        edges = list(CompatibilityEdge.objects.filter(from_part=pn)
                     .order_by('-is_mandatory', 'priority_rank')[:15])
        names = {p.tokin_part_no: p.display_name_vi
                 for p in Part.objects.filter(tokin_part_no__in=[e.to_part for e in edges])}
        results = [{'to_part': e.to_part, 'name': names.get(e.to_part, ''),
                    'is_mandatory': e.is_mandatory} for e in edges]
        return Response({'part': pn, 'results': results})

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

    @action(detail=False, methods=['get'], url_path='consumable-set', permission_classes=[IsAuthenticated])
    def consumable_set(self, request):
        """Bộ vật tư tiêu hao cho 1 model súng (nội bộ). ?model=TK-308RR.
        Khớp theo torch_models/set_id; nếu rỗng → suy hệ + dòng điện từ Torch rồi khớp set."""
        from apps.catalog.models import ConsumableSet
        model = (request.query_params.get('model') or '').strip().upper()
        sets = list(ConsumableSet.objects.prefetch_related('items'))
        sset = None
        if model:
            for cs in sets:
                if model in [str(t).upper() for t in (cs.torch_models or [])] or model in cs.set_id.upper():
                    sset = cs
                    break
            if sset is None:
                t = Torch.objects.filter(model_code__iexact=model).first()
                if t and getattr(t, 'ecosystem', '') and getattr(t, 'current_class', ''):
                    eco, cc = str(t.ecosystem).upper(), str(t.current_class).upper().replace('A', '')
                    for cs in sets:
                        if (str(cs.ecosystem).upper() == eco
                                and cc in str(cs.torch_current_class).upper()):
                            sset = cs
                            break
        if sset is None:
            avail = [{'set_id': s.set_id, 'name': s.display_name_vi}
                     for s in ConsumableSet.objects.all()[:8]]
            return Response({'matched': False, 'available': avail})
        items = sset.items.order_by('-is_mandatory', 'priority_rank')
        return Response({
            'matched': True, 'set_id': sset.set_id, 'name': sset.display_name_vi,
            'items': [{'part_no': it.part_no, 'note': it.note, 'part_role': it.part_role,
                       'default_quantity': it.default_quantity, 'is_mandatory': it.is_mandatory}
                      for it in items],
        })

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
