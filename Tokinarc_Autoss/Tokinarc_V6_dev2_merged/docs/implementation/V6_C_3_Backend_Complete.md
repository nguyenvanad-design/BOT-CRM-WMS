# Tokinarc V6.C.3 — Backend hoàn chỉnh (5 app còn lại)

Bổ sung **accounts, sales, analytics (CEO), storage, learning** — hoàn tất toàn bộ backend theo B.2/B.3. Tất cả viết theo đúng pattern crm/wms và **đã validate chạy thật**.

## Trạng thái toàn hệ

| App | Nguồn | Test |
| --- | --- | --- |
| common | bạn | — |
| catalog | bạn | — |
| crm | bạn (+ vá nhỏ) | 14 ✅ |
| wms | tôi (V6.C.2) | 11 ✅ |
| **accounts** | tôi | 6 ✅ |
| **sales** | tôi | 5 ✅ |
| **analytics (CEO)** | tôi | 4 ✅ |
| **storage** | tôi | 3 ✅ |
| **learning** | tôi | 2 ✅ |

**Tổng: 45 test pass** trên harness Django thật (sqlite, catalog stub đúng PK). Tất cả app mới tham chiếu catalog qua string FK `'catalog.Part'`/`'catalog.Torch'` nên chạy được với catalog thật của bạn không cần sửa.

## accounts — nền tảng auth (chặn mọi app khác)

- `User` (AbstractUser + `role` enum + `customer` FK) — single source cho phân quyền crm/wms/sales.
- Auth flow B.3 §2: `login` (có **account lockout** 5 lần/15 phút), `refresh` (rotation), `me`, `logout` (blacklist refresh).
- `/.well-known/jwks.json` cho sidecar verify (RS256 → JWK; HS256 dev → keys rỗng).
- `set-role` (admin only) + audit.
- `seed_users_roles` tạo admin + user mẫu mỗi role.
- **Bug đã sửa khi validate**: circular dependency `accounts.User.customer` ↔ `crm.Customer.owner` → tách **2 migration** (`0001` tạo User, `0002` thêm customer FK sau khi crm tồn tại). Đây là pattern bắt buộc cho FK vòng.

## sales — đơn bán + hợp đồng (gộp 4B.4)

- `SalesOrder` (one_off / framework trong 1 bảng), `SalesOrderLine`, `Payment`.
- `services.py`: `line_total` và `total_vnd` **luôn do BE tính** (chống FE gửi sai); `record_payment` chặn vượt total + tự chuyển `completed`.
- Actions: `sign` → `ship` (publish `OrderCreated`) → `cancel`; `debt-aging`, `summary`.
- Công nợ **derived** (`total - paid`), không bảng debt riêng.
- **Bug đã sửa**: property `debt_vnd` xung đột annotation cùng tên → đổi thành `debt_amount` (giống lỗi WMS trước).

## analytics (CEO) — dashboard, chỉ đọc, manager+

- `services.py` tính trực tiếp từ bảng live: `kpi_overview`, `revenue_monthly`, `revenue_by_segment`, `debt_aging`, `inventory_value`, `pipeline_forecast`.
- Permission `IsManagerOrAdmin` (sale/khách bị chặn).
- `refresh_mv` command cho production (REFRESH MATERIALIZED VIEW) — bật khi MV đã tạo qua SQL migration.
- **Không có models** (đúng — analytics là tầng đọc). Import Lead/Opportunity **phòng thủ** vì CRM hiện chưa có 2 model đó.

## storage — MinIO từ đầu

- `FileObject` (backend default `'s3'`), `save_upload` đẩy MinIO + **dedup theo sha256**; fallback `'local'` khi chưa cấu hình MinIO (dev/test).
- `upload/` (multipart) + `files/{id}/` read-only.

## learning — vòng học offline

- `QueryLog`, `GoldenExample`, `EventDeadLetter`.
- `run_critic_batch` (chấm điểm Flash, hàm `score_one` tách để mock), `promote_golden` (gate score≥4 & conf≥0.85, idempotent).
- Few-shot bơm ngược Planner: sidecar đọc `GoldenExample` active gần nhất theo embedding query.

## Wiring (settings + urls)

```python
# tokinarc/settings/base.py
INSTALLED_APPS += [
    'rest_framework_simplejwt', 'rest_framework_simplejwt.token_blacklist',
    'apps.accounts', 'apps.sales', 'apps.analytics', 'apps.storage', 'apps.learning',
]
AUTH_USER_MODEL = 'accounts.User'
```
```python
# tokinarc/urls.py
path('api/v1/auth/',      include('apps.accounts.auth_urls')),
path('api/v1/accounts/',  include('apps.accounts.urls')),
path('api/v1/sales/',     include('apps.sales.urls')),
path('api/v1/analytics/', include('apps.analytics.urls')),
path('api/v1/storage/',   include('apps.storage.urls')),
path('.well-known/jwks.json', JWKSView.as_view()),
```

## Bản vá CRM (kèm trong gói)

`crm_serializers_patched.py`: thêm `extra_kwargs = {'owner': {'required': False}}` vào `CustomerDetailSerializer.Meta` — để `perform_create` gán owner mặc định (trước đó serializer bắt buộc owner nên POST tạo KH trả 400). Áp patch này vào `apps/crm/serializers.py` của bạn.

## Thứ tự migrate

```bash
python manage.py makemigrations
python manage.py migrate           # accounts.0001 → crm → accounts.0002 → sales → ...
python manage.py seed_users_roles --admin-password=...
python manage.py seed_warehouse    # từ wms (V6.C.2)
pytest apps/ -q                    # 45 pass
```

## Còn lại để khớp 100% tài liệu (ngoài phạm vi backend chạy được)

CRM bạn upload mới có **Customer + Contact**. Tài liệu B.2 §4 còn: Lead, Opportunity, Quote/QuoteLine, Visit, Activity, ServiceTicket, Warranty, InstalledMachine. Khi thêm, `analytics.pipeline_forecast` (cần Opportunity) và `crm /360/` (cần orders/tickets) tự sáng. Sales `quote→order` (B.3 §3.3 `to-contract`) cũng chờ Quote. Các app tôi viết đã để hook/placeholder sẵn cho những phần này.
