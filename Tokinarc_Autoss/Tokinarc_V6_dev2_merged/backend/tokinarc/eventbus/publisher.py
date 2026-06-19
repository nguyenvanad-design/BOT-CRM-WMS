"""
Tokinarc V6.C-fix — tokinarc/eventbus/publisher.py

Postgres LISTEN/NOTIFY publisher. Service nội bộ gọi `publish(Channel.X, payload)`
thay vì viết SQL raw.

Đặc tả B.1 §5 + B.5 §4.

Đảm bảo idempotent + transaction-aware: dùng `transaction.on_commit()` để
NOTIFY chỉ phát ra sau khi commit thành công — tránh race với listener.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from django.db import connection, transaction

from .channels import ALL_CHANNELS, Channel

logger = logging.getLogger(__name__)


def publish(channel: str, payload: dict[str, Any]) -> None:
    """
    Schedule NOTIFY sau commit transaction hiện tại (hoặc immediate nếu
    không trong transaction).

    Args:
        channel: phải là một trong `ALL_CHANNELS` (constants tại `channels.py`)
        payload: JSON-serializable dict

    Raises:
        ValueError nếu channel không trong registry — fail loud để khỏi
        publish typo.
    """
    if channel not in ALL_CHANNELS:
        raise ValueError(
            f"Channel '{channel}' không có trong registry. "
            f"Thêm vào tokinarc/eventbus/channels.py trước."
        )

    msg = json.dumps(payload, default=str, ensure_ascii=False)

    def _notify():
        with connection.cursor() as cur:
            # pg_notify() an toàn hơn NOTIFY raw vì escape parameter đúng cách
            cur.execute("SELECT pg_notify(%s, %s)", [channel, msg])
        logger.info("event_published", extra={
            "channel": channel, "payload_size": len(msg),
        })

    transaction.on_commit(_notify)


# ─── Convenience wrappers ───────────────────────────────────────────────────
# Dùng trong service code để IDE autocomplete tốt hơn.
def publish_order_created(order_id: str, customer_id: str, total_vnd, **extra):
    publish(Channel.ORDER_CREATED, {
        'order_id': str(order_id), 'customer_id': str(customer_id),
        'total_vnd': str(total_vnd), **extra,
    })


def publish_payment_received(order_id: str, amount_vnd, method: str, **extra):
    publish(Channel.PAYMENT_RECEIVED, {
        'order_id': str(order_id), 'amount_vnd': str(amount_vnd),
        'method': method, **extra,
    })


def publish_stock_low(part_no: str, bin_code: str, qty_on_hand: int, min_level: int):
    publish(Channel.STOCK_LOW, {
        'part_no': part_no, 'bin_code': bin_code,
        'qty_on_hand': qty_on_hand, 'min_level': min_level,
    })


def publish_quote_approved(quote_id: str, customer_id: str, **extra):
    publish(Channel.QUOTE_APPROVED, {
        'quote_id': str(quote_id), 'customer_id': str(customer_id), **extra,
    })
