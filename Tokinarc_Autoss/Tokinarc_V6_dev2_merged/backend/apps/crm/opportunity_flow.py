"""
Tokinarc — apps/crm/opportunity_flow.py

KANBAN TỰ ĐỘNG: cơ hội tiến giai đoạn theo SỰ KIỆN NGHIỆP VỤ THẬT (không kéo thả):

    prospect  → qualify   : sale GHI NHẬN cuộc gặp/gọi (Visit/Activity gắn cơ hội)
    qualify   → proposal  : TẠO BÁO GIÁ cho cơ hội (auto-link nếu KH chỉ có 1 deal mở)
    proposal  → negotiate : báo giá ĐƯỢC DUYỆT (tự duyệt / L1 / L2)
    negotiate → won       : báo giá CHUYỂN THÀNH ĐƠN/HỢP ĐỒNG
    (bất kỳ)  → lost      : sale bấm 'Đánh dấu thua' — BẮT BUỘC chọn lý do

Quy tắc: chỉ TIẾN không tự LÙI; nhảy cóc được (vd tạo báo giá khi deal còn prospect
→ vào thẳng proposal); won/lost là trạng thái chốt — không auto rời. Mọi lần tiến
đều ghi AuditLog via='auto' (nguồn sự kiện nằm trong diff).
"""
from __future__ import annotations

_ORDER = ['prospect', 'qualify', 'proposal', 'negotiate', 'won']


def advance(opp, target: str, user=None, source: str = '') -> bool:
    """Đẩy cơ hội TIẾN tới `target` nếu đang ở giai đoạn thấp hơn. True nếu có đổi."""
    if opp is None:
        return False
    from apps.common.models import AuditLog

    from .models import OppStage

    if opp.stage in (OppStage.WON, OppStage.LOST):
        return False                                   # đã chốt — không auto rời
    try:
        cur, tgt = _ORDER.index(opp.stage), _ORDER.index(target)
    except ValueError:
        return False
    if tgt <= cur:
        return False                                   # không lùi / không đứng yên
    old = opp.stage
    opp.stage = target
    fields = ['stage', 'updated_at']
    if target == OppStage.WON and (opp.probability or 0) < 100:
        opp.probability = 100
        fields.append('probability')
    opp.save(update_fields=fields)
    AuditLog.objects.create(
        user=user if getattr(user, 'is_authenticated', False) else None,
        action='auto_stage', entity='Opportunity', entity_id=str(opp.id),
        diff={'from': old, 'to': target, 'source': source}, via='auto')
    return True


def opp_of_quote(quote):
    """Cơ hội gắn với báo giá. Nếu báo giá chưa gắn mà KH có ĐÚNG 1 deal đang mở
    → tự gắn (sale khỏi chọn tay); nhiều deal mở → không đoán (trả None)."""
    if quote.opportunity_id:
        return quote.opportunity
    from .models import Opportunity, OppStage
    opps = list(Opportunity.objects
                .filter(customer_id=quote.customer_id)
                .exclude(stage__in=[OppStage.WON, OppStage.LOST])[:2])
    if len(opps) == 1:
        quote.opportunity = opps[0]
        quote.save(update_fields=['opportunity', 'updated_at'])
        return opps[0]
    return None
