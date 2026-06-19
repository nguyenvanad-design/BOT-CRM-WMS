# Tokinarc V6.C.2 — WMS Implementation (app kho)

**Trạng thái trước**: tài liệu V6.B.2 mô tả WMS ở mức schema; **không có code**. Bộ V6.C bạn upload có catalog + crm nhưng **chưa có WMS**.

**Trạng thái sau**: app `apps/wms` đầy đủ, theo đúng pattern `apps/crm` đã thiết lập, **đã validate**: `makemigrations` sạch + 10 test pytest pass trên harness Django thật.

---

## 1. Đã tạo gì

| File | Nội dung |
| --- | --- |
| `models.py` | 14 model: Warehouse, Zone, Bin, InventoryItem, SerialNumber, Lot, ASN, InboundOrder/Line, OutboundOrder/Line, PickListItem, StockMovement + 6 enum |
| `services.py` | Logic tồn kho concurrency-safe: adjust, receive, transfer, generate_pick_list, confirm_pick_and_ship |
| `serializers.py` | List/detail + nested lines + action payloads (Adjust/Transfer) |
| `views.py` | 10 ViewSet khớp V6.B.3 §3.5 + multi-warehouse resolve + event publish hook |
| `permissions.py` | WMSPermission: customer bị chặn, đọc rộng / ghi hẹp (warehouse+) |
| `urls.py` | Router 10 resource |
| `migrations/0001_initial.py` | **Django tự sinh + validate**, kèm partial index low-stock |
| `tests/test_wms.py` | 10 test: XOR constraint, adjust/transfer, multi-wh filter, low_stock, permission |
| `management/commands/seed_warehouse.py` | Seed kho HCM mặc định + zone/bin |
| `apps.py`, `__init__.py` | App config |

## 2. Quyết định thiết kế bám tài liệu

- **Multi-warehouse từ đầu** (B.0 #7): Warehouse→Zone→Bin; `InventoryItem` gắn Bin, warehouse suy ra qua `bin.zone.warehouse`. Mọi endpoint nhận `?warehouse=<code>`; `resolve_warehouse()` auto chọn khi chỉ 1 kho active (FE ẩn switcher). **Không hardcode HCM** ở bất kỳ đâu.
- **Part XOR Torch**: `InventoryItem`, `InboundLine`, `OutboundLine` đều có CHECK constraint "đúng một trong hai not-null" (vá lỗ hổng nêu ở đánh giá B.2 §10). Đã test crash đúng khi cả hai null / cả hai set.
- **FK đúng PK catalog**: `part` → `catalog.Part` (PK `tokin_part_no`, `db_column='part_no'`), `torch` → `catalog.Torch` (PK `model_code`, `db_column='torch_model'`). Khớp models.py catalog bạn đã viết.
- **StockMovement append-only** = domain log của kho, tách khỏi AuditLog generic (không log đúp — đúng ghi chú B.2 §2).
- **Concurrency**: adjust/receive/transfer/pick dùng `select_for_update()` + cập nhật qty bằng `F()` expression tránh race read-modify-write.
- **Outbound rule** FIFO/FEFO/NEAREST: `generate_pick_list` phân bin theo rule, giữ tồn qua `qty_reserved`; `confirm_pick_and_ship` trừ tồn thực + cập nhật Serial status.
- **Event bus** (B.1 §5): `arrive`/`confirm`/`ship` gọi `_publish()` → nối vào `tokinarc.eventbus.publisher` (LISTEN/NOTIFY) khi sẵn sàng; hiện optional, không chặn.

## 3. Bug thật bắt được khi validate

Trong lúc chạy test harness, phát hiện và đã sửa: model `@property qty_available` **xung đột** với `.annotate(qty_available=...)` trong viewset (Django cố set annotation lên property → `AttributeError`). Đã đổi property thành `available_qty`, giữ annotation `qty_available` cho API. Đây là lỗi sẽ làm vỡ list endpoint ngay lần gọi đầu — nếu chỉ viết tài liệu sẽ không phát hiện.

## 4. Endpoint khớp contract (V6.B.3 §3.5)

`/api/v1/wms/`: warehouses, zones, bins, inventory (+adjust/+transfer), serials, lots, stock-movements, asn (+arrive), inbound (+confirm), outbound (+pick-list/+ship). Tất cả lọc theo `?warehouse=`.

## 5. Cách chạy

```bash
# wiring
# tokinarc/settings/base.py: INSTALLED_APPS += ['apps.wms']
# tokinarc/urls.py:          path('api/v1/wms/', include('apps.wms.urls')),

python manage.py makemigrations wms
python manage.py migrate
python manage.py seed_warehouse            # kho HCM mặc định
pytest apps/wms/tests/ -q
```

## 6. Còn thiếu để hoàn chỉnh toàn hệ (ngoài WMS)

WMS giờ ngang mức CRM. Để dev code trọn vẹn còn các app chưa có (theo B.2): **accounts** (User + role + JWKS — hiện crm/wms giả định đã có `User.role`), **sales** (SalesOrder/Payment — OutboundOrder đang link bằng `sales_order_code` string chờ app này), **analytics** (materialized views), **storage** (MinIO), **learning** (vòng học). Khuyến nghị thứ tự: accounts → sales → analytics → storage → learning, mỗi app theo đúng khuôn crm/wms này.
