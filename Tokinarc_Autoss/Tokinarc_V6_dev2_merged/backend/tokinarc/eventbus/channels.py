"""
Tokinarc V6.C-fix — tokinarc/eventbus/channels.py

**SINGLE SOURCE cho tên Postgres LISTEN/NOTIFY channels.**

Quy ước:
  - snake_case, lowercase (Postgres LISTEN case-insensitive cho identifier
    không quoted, nhưng quoted thì sensitive — luôn dùng lowercase để tránh bug).
  - Đặt tên theo dạng `<aggregate>_<past_tense>`: `order_created`, `payment_received`.
  - Payload luôn là JSON dict — không bao giờ raw string.

KHÔNG BAO GIỜ inline string channel name ở caller. Luôn:
    from tokinarc.eventbus.channels import Channel
    publish(Channel.ORDER_CREATED, {'order_id': order.id, ...})

Listener cũng phải dùng `Channel.X` để subscribe.
"""
from __future__ import annotations


class Channel:
    """Toàn bộ channel có thể NOTIFY/LISTEN. Thêm channel mới: thêm constant tại đây."""

    # ─── Sales ─────────────────────────────────────────────────────────────
    ORDER_CREATED        = 'order_created'
    ORDER_SIGNED         = 'order_signed'
    ORDER_SHIPPED        = 'order_shipped'
    ORDER_CANCELLED      = 'order_cancelled'
    ORDER_COMPLETED      = 'order_completed'
    PAYMENT_RECEIVED     = 'payment_received'

    # ─── CRM ───────────────────────────────────────────────────────────────
    QUOTE_CREATED        = 'quote_created'
    QUOTE_APPROVED       = 'quote_approved'
    QUOTE_CONVERTED      = 'quote_converted'     # → SalesOrder
    LEAD_QUALIFIED       = 'lead_qualified'
    OPPORTUNITY_STAGE    = 'opportunity_stage'   # payload có from→to
    TICKET_OPENED        = 'ticket_opened'
    TICKET_RESOLVED      = 'ticket_resolved'

    # ─── WMS ───────────────────────────────────────────────────────────────
    STOCK_MOVED          = 'stock_moved'
    STOCK_LOW            = 'stock_low'           # qty_on_hand ≤ min_level
    INBOUND_RECEIVED     = 'inbound_received'
    OUTBOUND_SHIPPED     = 'outbound_shipped'
    SERIAL_SOLD          = 'serial_sold'

    # ─── Auth / audit ──────────────────────────────────────────────────────
    USER_LOGGED_IN       = 'user_logged_in'
    USER_ROLE_CHANGED    = 'user_role_changed'

    # ─── Learning ──────────────────────────────────────────────────────────
    QUERY_LOGGED         = 'query_logged'
    GOLDEN_PROMOTED      = 'golden_promoted'


# Tập hợp tất cả channels để listener dễ subscribe toàn bộ (debugging).
ALL_CHANNELS: frozenset[str] = frozenset(
    v for k, v in vars(Channel).items()
    if not k.startswith('_') and isinstance(v, str)
)
