"""
Tokinarc V6.C-fix2 — apps/catalog/serializers.py

Serializer cho Part/Torch dùng ở 3 endpoint read-only chính:
  GET /api/v1/catalog/parts/search/   (list + search)
  GET /api/v1/catalog/parts/{id}/     (detail)
  GET /api/v1/catalog/torches/{id}/   (detail)

Triết lý:
  - Detail: trả full field (LLM cần context dày).
  - List/search: trả tóm tắt (LiteSerializer) để giảm payload.
  - Pricing đi qua `apps.catalog.pricing.get_effective_price()` — KHÔNG đọc
    trực tiếp `price_vnd` ở serializer (vaccine V2).
"""
from __future__ import annotations

from rest_framework import serializers

from apps.catalog.models import Part, Torch
from apps.catalog.pricing import format_price_vi, get_effective_price


# ─── Lite (list/search) ──────────────────────────────────────────────────────
class PartLiteSerializer(serializers.ModelSerializer):
    """Tóm tắt — dùng cho list/search. ~10 field thay vì 30+."""

    effective_price_vnd = serializers.SerializerMethodField()
    price_display       = serializers.SerializerMethodField()

    class Meta:
        model = Part
        fields = [
            'tokin_part_no', 'category', 'ecosystem', 'current_class',
            'display_name_vi', 'display_name_en',
            'effective_price_vnd', 'price_display', 'is_contact_price',
            'is_priority_sell',
        ]

    def get_effective_price_vnd(self, obj: Part):
        v = get_effective_price(obj)
        return int(v) if v else 0

    def get_price_display(self, obj: Part) -> str:
        if obj.is_contact_price:
            return 'Liên hệ'
        return format_price_vi(get_effective_price(obj))


class TorchLiteSerializer(serializers.ModelSerializer):
    effective_price_vnd = serializers.SerializerMethodField()
    price_display       = serializers.SerializerMethodField()

    class Meta:
        model = Torch
        fields = [
            'model_code', 'family', 'ecosystem', 'current_class', 'cooling',
            'display_name_vi', 'display_name_en',
            'rated_dc_a', 'duty_cycle_pct',
            'effective_price_vnd', 'price_display', 'is_contact_price',
            'is_priority_sell',
        ]

    def get_effective_price_vnd(self, obj: Torch):
        v = get_effective_price(obj)
        return int(v) if v else 0

    def get_price_display(self, obj: Torch) -> str:
        if obj.is_contact_price:
            return 'Liên hệ'
        return format_price_vi(get_effective_price(obj))


# ─── Detail (full) ───────────────────────────────────────────────────────────
class PartDetailSerializer(serializers.ModelSerializer):
    """Full field cho detail view. LLM context build từ đây."""

    effective_price_vnd = serializers.SerializerMethodField()
    price_display       = serializers.SerializerMethodField()

    class Meta:
        model = Part
        fields = '__all__'

    def get_effective_price_vnd(self, obj: Part):
        v = get_effective_price(obj)
        return int(v) if v else 0

    def get_price_display(self, obj: Part) -> str:
        if obj.is_contact_price:
            return 'Liên hệ'
        return format_price_vi(get_effective_price(obj))


class TorchDetailSerializer(serializers.ModelSerializer):
    effective_price_vnd = serializers.SerializerMethodField()
    price_display       = serializers.SerializerMethodField()

    class Meta:
        model = Torch
        fields = '__all__'

    def get_effective_price_vnd(self, obj: Torch):
        v = get_effective_price(obj)
        return int(v) if v else 0

    def get_price_display(self, obj: Torch) -> str:
        if obj.is_contact_price:
            return 'Liên hệ'
        return format_price_vi(get_effective_price(obj))
