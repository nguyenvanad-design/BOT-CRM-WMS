# Tokinarc V6 — Event Bus (Postgres LISTEN/NOTIFY)

## Quy tắc bắt buộc

1. **KHÔNG BAO GIỜ inline string channel name.** Luôn dùng `Channel.X` constant:

   ```python
   # ❌ SAI
   publish('order_created', {...})

   # ✅ ĐÚNG
   from tokinarc.eventbus.channels import Channel
   from tokinarc.eventbus.publisher import publish
   publish(Channel.ORDER_CREATED, {...})
   ```

2. **Thêm channel mới**: chỉ sửa `channels.py`. Không thêm rời rạc.

3. **Payload phải JSON-serializable dict.** Decimal/UUID → str ở caller.

4. **Publish trong transaction**: tự động dùng `on_commit` — KHÔNG fire trước khi commit.

5. **Channel name = snake_case lowercase.** Postgres LISTEN có quirks với quoted identifier.

## Cấu trúc file

```
tokinarc/eventbus/
├── channels.py     ← SINGLE SOURCE — danh sách channel
├── publisher.py    ← publish() + convenience wrappers
├── listener.py     ← @subscribe + run_listener() (worker process)
└── README.md       ← file này
```

## Thêm channel + handler mới

```python
# Bước 1 — tokinarc/eventbus/channels.py
class Channel:
    ...
    REFUND_REQUESTED = 'refund_requested'   # ← thêm dòng này

# Bước 2 — service code (ví dụ apps/sales/services.py)
from tokinarc.eventbus.publisher import publish
from tokinarc.eventbus.channels import Channel

def request_refund(order, amount, reason, user):
    # ... business logic ...
    publish(Channel.REFUND_REQUESTED, {
        'order_id': str(order.id),
        'amount_vnd': str(amount),
        'reason': reason,
        'by_user': user.id,
    })

# Bước 3 — handler (ví dụ apps/sales/event_handlers.py)
from tokinarc.eventbus.channels import Channel
from tokinarc.eventbus.listener import subscribe

@subscribe(Channel.REFUND_REQUESTED)
def notify_finance(payload: dict):
    # gửi mail/Slack cho finance team
    ...
```

## Listener process

```bash
# Trong worker container — entrypoint gọi:
python manage.py run_eventbus_listener
```

Listener auto-import mọi `apps/*/event_handlers.py` (Django ready signal) để
trigger `@subscribe` decorators.

## Dead letter

Handler throw exception → ghi `apps.learning.models.EventDeadLetter` để retry.
Cron `python manage.py replay_dead_letters` chạy hàng giờ.

## Khi nào KHÔNG dùng event bus

- Cần response sync ngay (HTTP request) — gọi service trực tiếp.
- Cần exactly-once semantic — dùng outbox table + dispatcher thay vì LISTEN/NOTIFY.
- Cross-region/cross-database — dùng Kafka/RabbitMQ (sau này nếu cần).
