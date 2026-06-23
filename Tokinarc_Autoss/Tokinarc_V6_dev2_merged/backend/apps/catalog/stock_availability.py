"""
Tokinarc V6.C — apps/catalog/stock_availability.py

Cổng READ HẸP cho BOT KHÁCH: chỉ trả TÌNH TRẠNG còn hàng (thô) theo mã part.
KHÔNG lộ số lượng chính xác / kho nào / vị trí ô / đơn / khách hàng.

  GET /api/v1/catalog/stock-availability/?parts=001002,002001
    header X-Intake-Key: <settings.LEAD_INTAKE_KEY>
  → {results: [{part, name, status, label}]}
     status ∈ in_stock | low_stock | out_of_stock | contact
"""
from __future__ import annotations

from django.conf import settings
from django.db.models import F, Sum
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

_LABEL = {
    'in_stock':     'Còn hàng',
    'low_stock':    'Sắp hết hàng',
    'out_of_stock': 'Hết hàng',
    'contact':      'Liên hệ để biết',
}


def _status_for(available: int | None, threshold: int) -> str:
    if available is None:
        return 'contact'          # part không có dữ liệu tồn
    if available <= 0:
        return 'out_of_stock'
    if available <= threshold:
        return 'low_stock'
    return 'in_stock'


class StockAvailabilityView(APIView):
    """Tình trạng còn hàng (thô) cho bot khách. Xác thực bằng X-Intake-Key."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        expected = getattr(settings, 'LEAD_INTAKE_KEY', '') or ''
        if not expected or request.headers.get('X-Intake-Key', '') != expected:
            return Response({'detail': 'Sai hoặc thiếu key.'}, status=401)

        from apps.catalog.models import Part
        from apps.wms.models import InventoryItem
        raw = request.query_params.get('parts') or request.query_params.get('part') or ''
        codes = [c.strip() for c in raw.split(',') if c.strip()][:50]
        if not codes:
            return Response({'detail': 'Thiếu tham số part(s).'}, status=400)

        threshold = int(getattr(settings, 'PUBLIC_LOW_STOCK_THRESHOLD', 10))
        names = dict(Part.objects.filter(tokin_part_no__in=codes)
                     .values_list('tokin_part_no', 'display_name_vi'))
        # Tồn khả dụng = Σ(qty_on_hand - qty_reserved) toàn hệ thống, theo part.
        agg = {row['part_id']: (row['avail'] or 0) for row in
               InventoryItem.objects.filter(part_id__in=codes)
               .values('part_id')
               .annotate(avail=Sum(F('qty_on_hand') - F('qty_reserved')))}

        results = []
        for code in codes:
            if code not in names:
                results.append({'part': code, 'name': '', 'status': 'contact',
                                'label': _LABEL['contact']})
                continue
            avail = agg.get(code)   # None nếu part chưa từng có tồn
            st = _status_for(avail, threshold)
            results.append({'part': code, 'name': names[code],
                            'status': st, 'label': _LABEL[st]})
        return Response({'results': results})
