# EVENTS & HANDLERS — Pattern async workflow

> **Cơ chế**: Postgres LISTEN/NOTIFY. Worker container chạy `manage.py run_eventbus_listener` long-running, mỗi handler đăng ký qua decorator `@subscribe(Channel.X)`.
> **Vai trò**: tách side-effect khỏi request HTTP (notification, recompute aggregate, sinh dữ liệu phụ).

---

## 1. Khi nào dùng event bus?

Quy tắc: nếu side-effect không cần đồng bộ với response → publish event.

| Use case | Sync (trong view) hay Async (handler)? |
|---|---|
| Cập nhật `paid_vnd` khi có payment | **Async** — không cần user chờ |
| Validate part_no có trong catalog không | **Sync** — phải trả 400 ngay |
| Gửi email khi quote approved | **Async** — không phải critical path |
| Trừ kho khi confirm xuất | **Sync** — phải atomic với order |
| Tự sinh `InstalledMachine` khi serial sold | **Async** — tracking, không critical |
| Cập nhật ranking sản phẩm hot | **Async** — batch tốt hơn |

---

## 2. Channel = SINGLE SOURCE

`backend/tokinarc/eventbus/channels.py` chứa **mọi** channel name. Đừng inline string.

```python
# tokinarc/eventbus/channels.py
class Channel:
    # Sales
    ORDER_CREATED       = 'order_created'
    ORDER_SIGNED        = 'order_signed'
    ORDER_SHIPPED       = 'order_shipped'
    PAYMENT_RECEIVED    = 'payment_received'

    # CRM
    LEAD_QUALIFIED      = 'lead_qualified'
    OPPORTUNITY_STAGE   = 'opportunity_stage'
    QUOTE_CREATED       = 'quote_created'
    QUOTE_APPROVED      = 'quote_approved'
    QUOTE_CONVERTED     = 'quote_converted'
    QUOTE_REJECTED      = 'quote_rejected'
    TICKET_OPENED       = 'ticket_opened'
    TICKET_RESOLVED     = 'ticket_resolved'

    # WMS
    STOCK_LOW           = 'stock_low'
    SERIAL_SOLD         = 'serial_sold'
    INVENTORY_TRANSFER  = 'inventory_transfer'


ALL_CHANNELS = frozenset({v for k, v in vars(Channel).items() if not k.startswith('_')})
```

**Naming**: `<aggregate>_<past_tense>`, lowercase. Past tense vì event = đã xảy ra.

---

## 3. Publish — Trong view / service

```python
# backend/apps/crm/services.py
from tokinarc.eventbus.channels import Channel
from tokinarc.eventbus.publisher import publish

@transaction.atomic
def approve_quote(quote: Quote, *, user) -> Quote:
    quote.status = QuoteStatus.APPROVED
    quote.approved_by = user
    quote.save()

    # Publish SAU khi commit để handler không thấy state cũ
    publish(Channel.QUOTE_APPROVED, {
        'quote_id': str(quote.id),
        'customer_id': str(quote.customer_id),
        'total_vnd': str(quote.total_vnd),
    })
    return quote
```

**Quy tắc publish**:
- Payload là `dict` JSON-serializable. UUID → `str()`. Decimal → `str()` hoặc `float()`.
- Publish **trong** `transaction.atomic` OK — publisher dùng `pg_notify` chạy ngay nhưng worker LISTEN sẽ nhận sau commit (PG đảm bảo).
- Đừng pass model object — handler có thể chạy ở worker khác process, model object không serialize được.

---

## 4. Subscribe — Trong app handlers.py

### Bước 1: Tạo `apps/<app>/handlers.py`

```python
# backend/apps/sales/handlers.py
"""
Tokinarc V6 — apps/sales/handlers.py
Handler async cho domain sales. Auto-import qua apps.ready().
"""
from __future__ import annotations

import logging
from decimal import Decimal

from tokinarc.eventbus.channels import Channel
from tokinarc.eventbus.listener import subscribe

logger = logging.getLogger(__name__)


@subscribe(Channel.PAYMENT_RECEIVED)
def on_payment_received(payload: dict) -> None:
    """
    Khi có payment mới, cập nhật SalesOrder.paid_vnd. Nếu paid_vnd >= total
    → status=COMPLETED.

    Idempotent — tính lại từ Sum(payment.amount_vnd) thay vì cộng dồn.
    """
    from django.db.models import Sum
    from apps.sales.models import OrderStatus, SalesOrder

    order_id = payload.get('order_id')
    if not order_id:
        logger.warning("payment_received_missing_order_id", extra={"payload": payload})
        return

    try:
        order = SalesOrder.objects.select_for_update().get(id=order_id)
    except SalesOrder.DoesNotExist:
        logger.warning("payment_received_order_not_found", extra={"order_id": order_id})
        return

    total_paid = order.payments.aggregate(s=Sum('amount_vnd'))['s'] or Decimal(0)
    order.paid_vnd = total_paid

    if order.paid_vnd >= order.total_vnd and order.status not in (
        OrderStatus.COMPLETED, OrderStatus.CANCELLED
    ):
        order.status = OrderStatus.COMPLETED

    order.save(update_fields=['paid_vnd', 'status', 'updated_at'])
    logger.info("payment_processed", extra={
        "order_code": order.code, "paid_vnd": str(order.paid_vnd),
    })


@subscribe(Channel.ORDER_SIGNED)
def on_order_signed(payload: dict) -> None:
    """Order ký xong → log + (mở rộng: gửi notification cho warehouse)."""
    logger.info("order_signed", extra=payload)
```

### Bước 2: Wire `apps.ready()` để auto-import

```python
# backend/apps/sales/apps.py
from django.apps import AppConfig


class SalesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.sales'
    verbose_name = 'Bán hàng & hợp đồng'

    def ready(self):
        """Import handlers để trigger @subscribe đăng ký vào listener registry."""
        try:
            from . import handlers  # noqa: F401
        except Exception:
            import logging
            logging.getLogger(__name__).exception("sales.handlers import failed")
```

Khi worker container chạy `python manage.py run_eventbus_listener`:
- Django bootstrap → `SalesConfig.ready()` import `handlers.py`
- `@subscribe(...)` decorator chạy → register function vào `_HANDLERS` dict
- Worker LISTEN trên các channel có handler

### Bước 3: Verify handler đã register

```bash
cd backend
DJANGO_SETTINGS_MODULE=tokinarc.settings.test python -c "
import django; django.setup()
from tokinarc.eventbus.listener import _HANDLERS
for ch, hs in sorted(_HANDLERS.items()):
    print(f'{ch}: {[h.__name__ for h in hs]}')
"
# → payment_received: ['on_payment_received']
# → order_signed: ['on_order_signed']
# ...
```

---

## 5. Test handler

Handler là function pure → test trực tiếp.

```python
# backend/apps/sales/tests/test_handlers.py
import pytest
from decimal import Decimal
from apps.sales.handlers import on_payment_received
from apps.sales.models import SalesOrder, OrderStatus, Payment
from apps.crm.tests.test_crm_ext import CustomerFactory, UserFactory


@pytest.mark.django_db
def test_payment_handler_completes_order_when_fully_paid():
    sale = UserFactory(role='sales')
    cust = CustomerFactory(owner=sale)
    order = SalesOrder.objects.create(
        code='HD-2026-0001', customer=cust, owner=sale,
        issued_date='2026-06-17',
        total_vnd=Decimal('1000000'), paid_vnd=Decimal(0),
        status=OrderStatus.ACTIVE,
    )
    # Tạo payment đủ tiền
    Payment.objects.create(order=order, amount_vnd=Decimal('1000000'),
                           paid_at='2026-06-17', method='transfer')

    # Gọi handler trực tiếp (bypass eventbus)
    on_payment_received({'order_id': str(order.id)})

    order.refresh_from_db()
    assert order.paid_vnd == Decimal('1000000')
    assert order.status == OrderStatus.COMPLETED


@pytest.mark.django_db
def test_payment_handler_idempotent():
    """Gọi handler 2 lần với cùng payment không double count."""
    # ...setup giống trên...
    on_payment_received({'order_id': str(order.id)})
    on_payment_received({'order_id': str(order.id)})  # call lại
    order.refresh_from_db()
    assert order.paid_vnd == Decimal('1000000')   # không phải 2M
```

> **Không test LISTEN/NOTIFY thật** trong unit test — SQLite không hỗ trợ. Integration test trên Postgres (CI) sẽ verify end-to-end.

---

## 6. Idempotency — Bắt buộc

Handler có thể chạy **nhiều lần** với cùng payload vì:
- Worker restart sau crash → re-process events trong dead letter queue
- 2 worker chạy song song (HA setup) → cùng nhận NOTIFY

→ Handler phải idempotent. Pattern:

### Pattern A: Recompute từ source (như `on_payment_received`)

```python
# THAY VÌ: order.paid_vnd += new_payment.amount_vnd   (cộng dồn → double count)
# DÙNG:
total_paid = order.payments.aggregate(s=Sum('amount_vnd'))['s'] or 0
order.paid_vnd = total_paid
```

### Pattern B: `get_or_create` (như `on_serial_sold`)

```python
@subscribe(Channel.SERIAL_SOLD)
def on_serial_sold(payload: dict) -> None:
    obj, created = InstalledMachine.objects.get_or_create(
        serial_no=payload['serial_no'],
        defaults={'customer_id': payload['customer_id'], ...}
    )
    if created:
        logger.info("installed_machine_created", extra=...)
```

### Pattern C: Idempotency key trong dead letter

Nếu có event cần đảm bảo "exactly once" (vd gửi email), lưu key vào table:

```python
class ProcessedEvent(models.Model):
    event_id = models.CharField(max_length=64, unique=True)
    processed_at = models.DateTimeField(auto_now_add=True)


@subscribe(Channel.QUOTE_APPROVED)
def send_quote_email(payload: dict):
    eid = f"quote_email_{payload['quote_id']}"
    if ProcessedEvent.objects.filter(event_id=eid).exists():
        return  # đã gửi rồi
    # Gửi email...
    ProcessedEvent.objects.create(event_id=eid)
```

---

## 7. Run listener trong dev

Test handler chạy với LISTEN/NOTIFY thật (cần Postgres):

```bash
# Terminal 1: Postgres
docker run --name pg-tokinarc -e POSTGRES_PASSWORD=tokinarc -p 5432:5432 -d pgvector/pgvector:pg16

# Terminal 2: Backend dev server (publish)
export DJANGO_SETTINGS_MODULE=tokinarc.settings.dev
export PGHOST=localhost PGDATABASE=postgres PGUSER=postgres PGPASSWORD=tokinarc
cd backend && python manage.py migrate && python manage.py runserver

# Terminal 3: Worker (listen)
cd backend && python manage.py run_eventbus_listener
# → "Listener khởi với 5 channel: ['order_created', 'order_signed', 'payment_received', ...]"

# Terminal 4: Trigger event qua API
TOKEN=$(...)
curl -X POST http://localhost:8000/api/v1/sales/payments/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"order": "<uuid>", "amount_vnd": 1000000, "paid_at": "2026-06-17", "method": "transfer"}'

# Quay lại terminal 3 — handler log:
# INFO payment_processed order_code=HD-2026-0001 paid_vnd=1000000
```

---

## 8. Specific channel với `--channels` flag

Khi debug 1 channel:

```bash
python manage.py run_eventbus_listener --channels=payment_received,order_signed
```

Worker chỉ LISTEN 2 channel này → log dễ đọc.

---

## 9. Bẫy thường gặp

### Bẫy 1: Handler đọc model state trước commit

```python
@subscribe(Channel.QUOTE_APPROVED)
def on_quote_approved(payload):
    quote = Quote.objects.get(id=payload['quote_id'])
    assert quote.status == 'approved'   # ← có thể fail nếu publish trước commit
```

**Fix**: publish **sau** `transaction.atomic` block, hoặc dùng `transaction.on_commit(lambda: publish(...))`.

### Bẫy 2: Handler crash → mất event

`listener.py` có dead letter queue đơn giản. Handler raise exception → log + bỏ qua event. Nếu cần retry, viết logic retry trong handler:

```python
@subscribe(Channel.QUOTE_APPROVED)
def send_email(payload):
    for attempt in range(3):
        try:
            external_email_api.send(...)
            return
        except APIError:
            if attempt == 2: raise
            time.sleep(2 ** attempt)
```

### Bẫy 3: Handler import circular

```python
# apps/sales/handlers.py
from apps.crm.models import InstalledMachine   # ← import top-level
```

→ Lúc Django bootstrap, sales.handlers chạy trước crm.models ready → ImportError.

**Fix**: import trong function body:

```python
@subscribe(Channel.SERIAL_SOLD)
def on_serial_sold(payload):
    from apps.crm.models import InstalledMachine   # lazy import
    InstalledMachine.objects.get_or_create(...)
```

### Bẫy 4: Channel typo

```python
publish('paymetn_received', {...})   # typo
```

→ Worker không LISTEN channel này → event mất. **Fix**: dùng `Channel.PAYMENT_RECEIVED` constant. Listener cũng validate qua `ALL_CHANNELS`.

### Bẫy 5: Handler ghi DB trong loop infinite

```python
@subscribe(Channel.QUOTE_APPROVED)
def trigger_workflow(payload):
    quote = Quote.objects.get(...)
    quote.notes += " [auto-processed]"
    quote.save()
    # → publish(Channel.QUOTE_UPDATED)
    # → handler khác listen QUOTE_UPDATED → cập nhật quote nữa → infinite loop
```

→ Đừng publish event từ trong handler. Nếu cần chain, design rõ ràng (vd publish 1 lần ở end-of-flow).

---

## 10. Materialized View refresh — Use case khác

MV không qua eventbus mà qua cron:

```bash
# infra/scripts/worker_entrypoint.sh
*/15 * * * * cd /app && python manage.py refresh_mv --group=hourly
0 2 * * *    cd /app && python manage.py refresh_mv --group=daily
```

Lý do: MV refresh cần lock table tạm, không phù hợp realtime. Cron 15 phút đủ cho dashboard CEO.

Xem `backend/apps/analytics/management/commands/refresh_mv.py` — đã có.

Khi cần MV mới:
1. Viết migration RunSQL `CREATE MATERIALIZED VIEW mv_xxx AS SELECT ...` (xem `EXTENDING.md` §9.1 nếu liên quan pgvector).
2. Thêm vào `HOURLY` hoặc `DAILY` list trong `refresh_mv.py`.
3. Service `analytics/services.py` query MV thay raw table.

---

## 11. Checklist khi thêm event mới

```
□ Thêm Channel.X constant trong tokinarc/eventbus/channels.py
□ Publish trong view/service (sau transaction.atomic commit)
□ Tạo apps/<app>/handlers.py với @subscribe(Channel.X)
□ Wire apps/<app>/apps.py def ready() import handlers
□ Verify handler register: list _HANDLERS dict
□ Test handler unit (gọi function trực tiếp, mock dependencies)
□ Đảm bảo handler idempotent (test gọi 2 lần)
□ Integration test trên Postgres (LISTEN/NOTIFY thật) — chỉ CI
□ Update EVENTS_HANDLERS.md nếu pattern mới
```

---

## 12. Roadmap event bus

Hiện trạng: channels.py có đủ + 5 handler mẫu (payment_received, order_created, order_signed, stock_low, serial_sold). Chưa wire production.

Việc tiếp:
1. **Notification handlers**: gửi email/Zalo khi quote approved, ticket opened
2. **Stock low alert**: handler tự sinh purchase request từ template
3. **Embedding update**: khi part thêm/sửa, publish `PART_UPDATED` → handler chạy lại BGE-M3 cho part đó (tránh reseed full)
4. **Audit log async**: hiện AuditLog ghi sync trong view; có thể chuyển async để response nhanh hơn
