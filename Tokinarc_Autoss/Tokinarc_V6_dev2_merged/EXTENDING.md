# EXTENDING — Hướng dẫn mở rộng Tokinarc V6 không gây xung đột

> Mục tiêu: thêm tính năng mới (app, model, role, channel, endpoint, tool chatbot,
> page FE) mà **không phá logic cũ** và **không gây xung đột dữ liệu / migration**.
> Tài liệu này mô tả các "khớp nối mở" có sẵn và các bẫy đã biết. Đọc trước khi code.
>
> **Bổ sung**: chi tiết thêm tool chatbot xem [`docs/dev/CHATBOT_TOOL_GUIDE.md`](docs/dev/CHATBOT_TOOL_GUIDE.md).
> Chi tiết FE: [`docs/dev/FRONTEND_GUIDE.md`](docs/dev/FRONTEND_GUIDE.md).

---

## 0. Nguyên tắc chung

Kiến trúc này **cộng thêm (additive)**, không sửa lõi. Đồ thị phụ thuộc một chiều:

```
common  ←  catalog · accounts
   ↑            ↑
crm · wms · sales · analytics · storage · learning
```

- `common` không import app nào khác. `catalog`/`accounts` chỉ dựa vào `common`.
- App nghiệp vụ trỏ lên trên (sales → crm + catalog + accounts), **không bao giờ ngược lại**.
- Quy tắc vàng: **thêm cái mới, đừng sửa cái đang chạy**. Nếu buộc phải sửa model/endpoint
  cũ, coi đó là thay đổi có chủ đích (breaking) và làm theo Mục 7.

Trước khi mở PR, chạy đủ 4 lệnh ở **Mục 8 — Checklist bắt buộc**. Nếu cả 4 xanh,
gần như chắc chắn không xung đột.

---

## 1. Thêm một app nghiệp vụ mới

Làm theo đúng khuôn `crm`/`wms` (2 app mẫu chuẩn). Cấu trúc tối thiểu:

```
apps/<newapp>/
  __init__.py
  apps.py            # AppConfig, default_auto_field
  models.py          # kế thừa BaseModel/SoftDeleteMixin từ apps.common.models
  serializers.py
  views.py           # ViewSet, lọc theo ?warehouse= nếu liên quan kho
  permissions.py     # import Role từ apps.accounts.roles — KHÔNG redefine
  urls.py            # router.register(...)
  migrations/__init__.py
  tests/__init__.py
  tests/test_<newapp>.py
```

Wire 2 chỗ, **không đụng file nào khác**:

```python
# tokinarc/settings/base.py
INSTALLED_APPS += ['apps.<newapp>']

# tokinarc/urls.py
path('api/v1/<newapp>/', include('apps.<newapp>.urls')),
```

Sau đó: `makemigrations <newapp>` → `migrate` → viết test → chạy Mục 8.

---

## 2. Thêm model — quy ước bắt buộc

- **Entity nghiệp vụ** → kế thừa `BaseModel` (PK = UUID7, có `created_at/by`,
  `updated_at/by`) và thêm `SoftDeleteMixin` nếu cần xóa mềm.
- **KHÔNG dùng `BaseModel` cho**: bảng catalog (PK là string cố định như
  `tokin_part_no`/`model_code`) và bảng audit/log (dùng `BigAutoField`).
- Mọi model khai `db_table` tường minh (`<app>_<tên>`), giống các app hiện có.
- **Index phải đặt tên tường minh** (`name='...'`). Index không tên khiến Django
  tự sinh tên hash → **drift migration** mỗi lần đổi field. Đây chính là bug đã
  từng xảy ra ở catalog.

```python
class Meta:
    db_table = 'newapp_thing'
    indexes = [
        models.Index(fields=['status', 'created_at'], name='newapp_thing_status_idx'),
    ]
```

---

## 3. Liên kết sang app khác — FK hay loose key?

Hai kiểu liên kết đang dùng, chọn đúng kiểu:

- **Hard FK** (`ForeignKey('app.Model')`): dùng khi quan hệ chắc chắn và muốn DB
  bảo toàn toàn vẹn. Ví dụ: `sales.SalesOrderLine.part → catalog.Part`.
  Dùng `on_delete=PROTECT` cho dữ liệu nghiệp vụ (đừng `CASCADE` xóa lan).
- **Loose key** (`CharField` chứa mã, có `db_index`): dùng khi app đích **chưa
  tồn tại** hoặc muốn tránh phụ thuộc seed-order. Ví dụ hiện tại:
  `wms.OutboundOrder.sales_order_code` (string, vì Quote/SalesOrder chưa đủ).

**Bẫy dữ liệu:** khi nâng một loose key thành hard FK (xem Mục 7), phải migrate
dữ liệu cũ và cập nhật mọi chỗ đang join bằng string. Đừng đổi lặng lẽ.

---

## 4. Thêm / sửa phân quyền (role)

**SINGLE SOURCE OF TRUTH = `apps/accounts/roles.py`.** Không định nghĩa role,
hierarchy hay map quyền ở bất kỳ đâu khác.

- Thêm role mới: thêm hằng trong `class Role`, thêm vào `ALL_ROLES` và
  `ROLE_HIERARCHY`. Tất cả `permissions.py` của các app import lại tự động.
- Thêm quyền cho tool chatbot: thêm dòng vào `WRITE_TOOL_REQUIREMENTS`
  (tool ghi), `READ_TOOLS` + `READ_TOOL_REQUIREMENTS` (tool đọc nhạy cảm như
  tài chính), hoặc chỉ `READ_TOOLS` (tool đọc thường, mọi role nội bộ dùng được).
- Tách nhóm quyền mới (vd tách nhập kho khỏi manager): thêm 1 frozenset mới
  (vd `PURCHASING_ROLES = frozenset({Role.ADMIN, Role.WAREHOUSE})`) rồi đổi giá
  trị các dòng tương ứng trong `READ_TOOL_REQUIREMENTS`. **Không** sửa
  `tool_guardrail.py` hay frontend — chúng đọc động từ bảng.
- Trong `permissions.py` của app, chỉ **import** `Role`, `role_of`, `has_role`,
  `is_manager` — theo mẫu `wms/permissions.py` ("đọc rộng, ghi hẹp").

**Sau MỌI thay đổi roles.py → regenerate file cho chatbot/frontend (1 lệnh):**

```bash
cd backend
python manage.py dump_roles --format=py --out ../chatbot/roles_generated.py
python manage.py dump_roles --format=ts --out ../frontend/src/lib/auth/roles.ts   # khi FE sẵn sàng
```

CI tự chặn nếu quên regenerate (bước "Check role tables sync"). Vì quyền tập
trung một chỗ + sinh tự động, thêm/tách role **không xung đột** với app cũ.

---

## 5. Thêm sự kiện async (eventbus LISTEN/NOTIFY)

**SINGLE SOURCE = `tokinarc/eventbus/channels.py`.**

- Thêm channel: thêm constant `class Channel` (dạng `<aggregate>_<past_tense>`,
  lowercase, ví dụ `ticket_resolved`).
- Publish: `publish(Channel.TICKET_RESOLVED, {'ticket_id': ...})` — payload luôn
  là JSON dict. **Không bao giờ inline string channel** ở caller.
- Listener subscribe cũng dùng `Channel.X`.

Worker (`run_eventbus_listener`) đã chạy sẵn; thêm channel mới không phá listener cũ.

---

## 6. Thêm tool cho chatbot / endpoint mới

- Chatbot có nếp **version**: `/api/v2` là pipeline chính, `/api/v5` forward về v2.
  Đổi pipeline thì giữ route cũ forward sang route mới — **không phá client cũ**.
- Tool chatbot gọi ngược Django REST. Thêm tool đọc → thêm vào `READ_TOOLS`.
  Thêm tool ghi → thêm vào `WRITE_TOOL_REQUIREMENTS` (Mục 4) để guardrail chặn role.
- Endpoint Django mới: thêm trong `urls.py` của app, không sửa root trừ khi thêm
  app (Mục 1).

---

## 7. Khi BUỘC phải thay đổi cái đang chạy (breaking change)

Áp dụng khi: nâng loose key → FK, đổi field, đổi nghĩa endpoint.

1. Viết migration **riêng** (`makemigrations`), không sửa migration `0001` cũ.
2. Nếu cần chuyển dữ liệu: dùng `RunPython` có hàm forward **và** reverse.
3. Với endpoint: giữ bản cũ (deprecate), thêm bản mới — đừng đổi nghĩa tại chỗ.
4. Cập nhật test cũ + thêm test mới. Chạy Mục 8.

---

## 8. ⚠️ CHECKLIST BẮT BUỘC trước khi merge

Chạy đủ 4 lệnh. Tất cả phải xanh:

```bash
cd backend

# 1) Không lệch model ↔ migration (chặn drift — bug đã từng xảy ra ở catalog)
python manage.py makemigrations --check --dry-run

# 2) Migrate chạy sạch (dev/test dùng SQLite, prod/CI dùng Postgres)
python manage.py migrate

# 3) Toàn bộ test qua đường migration thật (KHÔNG để pytest né bằng syncdb)
pytest apps/ --create-db -q

# 4) Lint
ruff check .
```

Nếu lệnh (1) báo "Migrations for ..." → **có drift**, sửa trước khi merge
(thường do quên đặt tên index — xem Mục 2).

---

## 9. ⚠️ BẪY ĐÃ BIẾT — đọc kỹ, đây là nơi dễ vỡ nhất

### 9.1 Đụng tới `catalog.PartEmbedding` → phải tự guard vendor

`catalog/migrations/0001_initial.py` dùng `SeparateDatabaseAndState` cho bảng
`catalog_part_embedding`: **state** là schema Postgres chuẩn (`VectorField(1024)`
+ `HnswIndex`), nhưng **database** rẽ nhánh theo vendor (Postgres → vector thật +
HNSW; SQLite → cột text, bỏ HNSW).

> Nếu bạn `AddField`/`AddIndex`/đổi gì đó trên `PartEmbedding` và để Django
> **auto-generate migration**, nó sẽ nhét `vector`/HNSW vô điều kiện và **vỡ trên
> SQLite** y như bug cũ (`OperationalError: near "EXTENSION"`).

Cách đúng: viết migration tay, bọc phần pgvector trong `RunPython` có guard:

```python
def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("ALTER TABLE catalog_part_embedding ADD COLUMN ...")
    else:
        schema_editor.execute("ALTER TABLE catalog_part_embedding ADD COLUMN ... text")
```

Các bảng catalog **khác** (Torch, Part, edge...) auto-migrate bình thường — bẫy
này **chỉ** áp dụng cho `PartEmbedding`.

### 9.2 Vector search KHÔNG chạy trên SQLite

Trên SQLite cột `vector` là text → không query vector được. Tính năng dựa trên
semantic search (gợi ý sản phẩm, RAG) **chạy đúng trên Postgres** nhưng **test
SQLite không phản ánh được**.

> Đừng tin test SQLite là đủ cho tính năng vector. Phải test nhánh đó trên
> Postgres thật (CI đã dùng image `pgvector/pgvector:pg16` — viết test vector
> chạy trong CI, đừng chỉ chạy local SQLite).

### 9.3 Đừng sửa `0001_initial` của bất kỳ app nào

Nhiều app depend `catalog.0001_initial` / `accounts.0001` theo **tên**. Sửa nội
dung migration đã commit sẽ làm lệch lịch sử ở máy đã migrate. Luôn thêm
migration mới (`0002_...`), không sửa cái cũ.

### 9.4 PK của catalog là string, không phải UUID

FK trỏ tới catalog phải dùng đúng PK string: `Torch` = `model_code`,
`Part` = `tokin_part_no`. Đừng giả định UUID như các bảng `BaseModel`.

---

## 10. Khuyến nghị: bổ sung 1 dòng vào CI

CI hiện chạy `migrate` + `pytest` trên Postgres (tốt — có chạy nhánh vector),
nhưng **thiếu check drift**. Thêm bước này vào `.github/workflows/ci.yml`
(trước `pytest`) để bẫy 9.1/9.3 tự động, vĩnh viễn:

```yaml
      - name: Check migrations drift
        working-directory: backend
        run: python manage.py makemigrations --check --dry-run
```

---

## Tóm tắt 1 dòng

Thêm app/role/channel/endpoint **theo khuôn** thì không va chạm. Rủi ro thật chỉ
ở: (a) động vào `PartEmbedding` mà quên guard vendor, (b) nâng loose-key thành FK
khi viết CRM mở rộng, (c) quên đặt tên index gây drift. Cả ba đều tránh được nếu
chạy đủ Checklist Mục 8 và đọc Bẫy Mục 9.

---

## Tham khảo chi tiết

| Bạn muốn làm gì | Đọc file |
|---|---|
| Thêm tool chatbot mới end-to-end | [`docs/dev/CHATBOT_TOOL_GUIDE.md`](docs/dev/CHATBOT_TOOL_GUIDE.md) |
| Thêm page FE mới + theme | [`docs/dev/FRONTEND_GUIDE.md`](docs/dev/FRONTEND_GUIDE.md) |
| Thêm event/handler async | [`docs/dev/EVENTS_HANDLERS.md`](docs/dev/EVENTS_HANDLERS.md) |
| Tra cứu endpoint backend | [`docs/dev/API_REFERENCE.md`](docs/dev/API_REFERENCE.md) |
| Hiểu data flow toàn hệ thống | [`docs/architecture/Tokinarc_V6_LLD_DataFlow.md`](docs/architecture/Tokinarc_V6_LLD_DataFlow.md) |
| Gặp lỗi khi chạy | [`docs/dev/TROUBLESHOOTING.md`](docs/dev/TROUBLESHOOTING.md) |
