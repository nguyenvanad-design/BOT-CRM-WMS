# TOKINARC — V6.B.2 · Database schema & Django models

**Postgres 16 + pgvector · 8 app · ~37 model · materialized views · LISTEN/NOTIFY triggers**

Phụ thuộc: V6.B.1 (Stack & Topology) · V6 gốc Mục 4B.4 (gộp Sales Orders)

Ngày soạn: 16/06/2026 · Phiên bản: 1.0

---

## Mục lục

1. Nguyên tắc chung & convention
2. App accounts — User, AuditLog
3. App catalog — Parts, Torches, Edges, Embeddings **+ 5 nhóm bổ sung**
4. App crm
5. App sales (gộp 4B.4)
6. App wms (multi-warehouse)
7. App analytics — Materialized views
8. App storage — FileObject (MinIO)
9. App learning — Query log, Critic, Golden Store (vòng học)
10. Indexes, constraints, performance
11. Migration & seed strategy

---

## 1. Nguyên tắc chung & convention

- **Một Postgres database, một schema** (`public`). Chia logic bằng app prefix (`{app}_{model}`).
- **BaseModel** (`apps/common/models.py`): mọi entity nghiệp vụ kế thừa — `id` (UUID7), `created_at`, `updated_at`, `created_by`, `updated_by`.
- **Soft delete**: chỉ Customer, SalesOrder, SerialNumber. Còn lại hard delete.
- **UUID7** thay autoincrement — sort theo time, không lộ thứ tự nghiệp vụ. **Lib đã chốt: `uuid6`** (`pip install uuid6`, hàm `uuid6.uuid7()`). Không dùng uuid4 làm tạm rồi đổi sau.
- **Enum**: `TextChoices` (lưu string), debug dễ.
- **Money**: `DecimalField(max_digits=14, decimal_places=0)` cho VND.
- **Timestamp**: UTC trong DB, convert Asia/Ho_Chi_Minh ở serializer.

```python
# apps/common/models.py
from uuid6 import uuid7          # pip install uuid6 — sinh UUID7 (time-ordered)
from django.db import models
from django.conf import settings

class BaseModel(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name='+', editable=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name='+', editable=False)
    class Meta: abstract = True

class SoftDeleteMixin(models.Model):
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name='+')
    class Meta: abstract = True
```

---

## 2. App accounts — User, AuditLog

```python
# apps/accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    phone    = models.CharField(max_length=20, blank=True)
    role     = models.CharField(max_length=20, choices=[
        ('customer','Khách hàng'), ('sales','Sales'), ('warehouse','Nhân viên kho'),
        ('service','Kỹ sư dịch vụ'), ('manager','Quản lý'), ('admin','Admin'),
    ], default='sales', db_index=True)
    customer = models.ForeignKey('crm.Customer', null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name='users')

class AuditLog(models.Model):
    """Append-only. Log mọi hành động ghi. via phân biệt nguồn ui/bot/api/cron."""
    id        = models.BigAutoField(primary_key=True)
    ts        = models.DateTimeField(auto_now_add=True, db_index=True)
    user      = models.ForeignKey(User, on_delete=models.PROTECT, null=True)
    action    = models.CharField(max_length=40, db_index=True)   # create/update/delete/approve
    entity    = models.CharField(max_length=40, db_index=True)   # 'sales.SalesOrder'
    entity_id = models.CharField(max_length=64, db_index=True)
    diff      = models.JSONField(default=dict)                   # {before, after}
    ip        = models.GenericIPAddressField(null=True)
    via       = models.CharField(max_length=20, default='ui')    # ui/bot/api/cron
    class Meta:
        indexes = [models.Index(fields=['entity', 'entity_id', '-ts'])]
```

Role là enum string, không bảng Role/Permission riêng. Object-level ("sale chỉ xem KH của mình") làm bằng queryset filter trong viewset. Audit trigger qua signal `post_save`/`post_delete` trên model có `AuditMixin`.

> **AuditLog (generic) vs StockMovement / Payment (domain-specific)**: AuditLog ghi *mọi* entity cho mục đích truy vết/bảo mật; StockMovement ghi *riêng* biến động tồn cho nghiệp vụ kho. Đừng log đúp — domain log không cần ghi lại vào AuditLog.

---

## 3. App catalog — Parts, Torches, Edges, Embeddings + 5 nhóm bổ sung

Port toàn bộ `tokinarc_data_v19.json` (**12 nhóm**). V6.A chỉ model 6 nhóm — đây là phần **bổ sung 5 nhóm còn thiếu** (negative_rules, process_edges, gas_flow_edges, consumable_sets, category_vocabulary; cộng aliases + index).

### 3.1 Nhóm lõi (đã có ở V6.A)

```python
# apps/catalog/models.py
from django.db import models
from pgvector.django import VectorField, HnswIndex

class Torch(models.Model):
    model_code    = models.CharField(max_length=40, primary_key=True)   # 'TK-508RR'
    display_name  = models.CharField(max_length=200)
    ecosystem     = models.CharField(max_length=10, db_index=True)      # 'N','WX','TIG','HYBRID'
    current_class = models.CharField(max_length=20, db_index=True)      # '350A','500A'
    body_type     = models.CharField(max_length=20)                     # robotic/manual/tig
    process       = models.JSONField(default=list)
    notes         = models.TextField(blank=True)

class Part(models.Model):
    tokin_part_no  = models.CharField(max_length=40, primary_key=True)  # '002001'
    category       = models.CharField(max_length=40, db_index=True)
    ecosystem      = models.CharField(max_length=10, db_index=True)
    current_class  = models.CharField(max_length=20, db_index=True)
    display_name_vi= models.CharField(max_length=200)
    display_name_en= models.CharField(max_length=200)
    wire_size_mm   = models.DecimalField(max_digits=4, decimal_places=2, null=True)
    total_length_mm= models.IntegerField(null=True)
    thread_type    = models.CharField(max_length=20, blank=True)
    material       = models.CharField(max_length=40, blank=True)
    p_part_nos     = models.JSONField(default=list)   # Panasonic eq
    d_part_nos     = models.JSONField(default=list)   # Daihen eq
    o_part_nos     = models.JSONField(default=list)   # Others
    price_vnd        = models.DecimalField(max_digits=14, decimal_places=0, null=True)
    price_unit       = models.CharField(max_length=10, default='cái')
    price_note       = models.TextField(blank=True)
    is_contact_price = models.BooleanField(default=False)
    is_priority_sell = models.BooleanField(default=False)
    price_updated    = models.CharField(max_length=10, blank=True)
    source         = models.CharField(max_length=40, blank=True)
    confidence     = models.DecimalField(max_digits=3, decimal_places=2, default=1.0)
    class Meta:
        indexes = [models.Index(fields=['category','ecosystem']),
                   models.Index(fields=['ecosystem','current_class','category'])]

class CompatibilityEdge(models.Model):
    id        = models.BigAutoField(primary_key=True)
    src       = models.CharField(max_length=40, db_index=True)
    src_kind  = models.CharField(max_length=10)      # 'part'/'torch'
    dst       = models.CharField(max_length=40, db_index=True)
    dst_kind  = models.CharField(max_length=10)
    edge_type = models.CharField(max_length=20, db_index=True)   # fits/used_with/incompatible
    note      = models.CharField(max_length=200, blank=True)
    class Meta:
        unique_together = [('src','dst','edge_type')]
        indexes = [models.Index(fields=['src','edge_type'])]

class TorchPartMapping(models.Model):
    torch     = models.ForeignKey(Torch, on_delete=models.CASCADE, related_name='part_mappings')
    part      = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='torch_mappings')
    role      = models.CharField(max_length=40)      # tip/nozzle/body
    is_default= models.BooleanField(default=False)
    class Meta:
        unique_together = [('torch','part','role')]

class PartEmbedding(models.Model):
    part      = models.OneToOneField(Part, on_delete=models.CASCADE, primary_key=True, related_name='embedding')
    text_hash = models.CharField(max_length=64, db_index=True)   # skip re-embed nếu chưa đổi
    vector    = VectorField(dimensions=1024)                     # BGE-M3
    model_ver = models.CharField(max_length=40, default='BAAI/bge-m3')
    updated_at= models.DateTimeField(auto_now=True)
    class Meta:
        indexes = [HnswIndex(name='part_emb_hnsw', fields=['vector'],
                             m=16, ef_construction=64, opclasses=['vector_cosine_ops'])]

class AssemblyProcedure(models.Model):
    id         = models.CharField(max_length=40, primary_key=True)
    kind       = models.CharField(max_length=20, db_index=True)  # troubleshooting/replacement/...
    title      = models.CharField(max_length=200)
    body       = models.JSONField()
    applies_to = models.JSONField(default=list)
```

### 3.2 NHÓM BỔ SUNG (mới trong V6.B)

Các nhóm này **bot tư vấn cần** — thiếu sẽ gợi ý sai tương thích và mất khả năng upsell. Schema bám sát đúng JSON v19.

```python
# ── negative_rules (17): luật loại trừ tương thích ──────────────────
class NegativeRule(models.Model):
    rule_id          = models.CharField(max_length=60, primary_key=True)  # 'N_TIP_D_ORIFICE'
    description      = models.CharField(max_length=300)
    from_category    = models.CharField(max_length=40, db_index=True)     # 'Tip'
    to_category      = models.CharField(max_length=40, db_index=True)     # 'Orifice'
    from_ecosystem   = models.CharField(max_length=10)                    # 'N'
    to_ecosystem     = models.CharField(max_length=10)                    # 'D'
    relation_type    = models.CharField(max_length=30, default='incompatible_with')
    incompatibility_reason = models.TextField(blank=True)
    class Meta:
        indexes = [models.Index(fields=['from_category','to_category'])]

# ── process_edges (359): part hỗ trợ quy trình hàn nào ──────────────
class ProcessEdge(models.Model):
    id           = models.BigAutoField(primary_key=True)
    from_part    = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='process_edges')
    to_process   = models.CharField(max_length=20, db_index=True)        # 'CO2','MAG','MIG','TIG'
    relation_type= models.CharField(max_length=30, default='supports_process')
    is_preferred = models.BooleanField(default=False)
    source       = models.CharField(max_length=40, blank=True)
    class Meta:
        unique_together = [('from_part','to_process')]
        indexes = [models.Index(fields=['to_process','is_preferred'])]

# ── gas_flow_edges (24): orifice lắp vừa nozzle nào ─────────────────
class GasFlowEdge(models.Model):
    id            = models.BigAutoField(primary_key=True)
    from_orifice  = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='gas_flow_from')
    to_nozzle     = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='gas_flow_to')
    relation_type = models.CharField(max_length=30, default='fits_in_nozzle')
    reason        = models.CharField(max_length=300, blank=True)
    source        = models.CharField(max_length=40, blank=True)
    class Meta:
        unique_together = [('from_orifice','to_nozzle')]

# ── consumable_sets (9–20): bộ vật tư tiêu hao đi kèm (UPSELL) ───────
class ConsumableSet(models.Model):
    set_id              = models.CharField(max_length=60, primary_key=True)  # 'N350A_standard'
    display_name_vi     = models.CharField(max_length=200)
    torch_current_class = models.CharField(max_length=20, db_index=True)     # '350A'
    ecosystem           = models.CharField(max_length=10, db_index=True)
    cooling_method      = models.CharField(max_length=20, blank=True)        # 'air'/'water'
    default_wire_size_mm= models.DecimalField(max_digits=4, decimal_places=2, null=True)
    notes               = models.TextField(blank=True)

class ConsumableSetItem(models.Model):
    """Part nào thuộc set nào — quan hệ many-to-many có thuộc tính."""
    consumable_set = models.ForeignKey(ConsumableSet, on_delete=models.CASCADE, related_name='items')
    part           = models.ForeignKey(Part, on_delete=models.PROTECT, related_name='in_sets')
    role           = models.CharField(max_length=40, blank=True)   # tip/nozzle/orifice/liner
    qty            = models.IntegerField(default=1)
    class Meta:
        unique_together = [('consumable_set','part','role')]

# ── category_vocabulary (35): từ điển VI↔EN + aliases cho NLU ───────
class CategoryVocabulary(models.Model):
    en_term       = models.CharField(max_length=40, primary_key=True)   # 'Tip'
    vi_term       = models.CharField(max_length=80)                     # 'béc hàn'
    part_category = models.CharField(max_length=40, db_index=True)      # 'Tip'
    vi_aliases    = models.JSONField(default=list)                      # ['đầu hàn','mũi hàn',...]

# ── fake_pno_aliases (14): part-no giả → part thật ──────────────────
class PartNoAlias(models.Model):
    fake_pno = models.CharField(max_length=40, primary_key=True)   # '005001'
    primary  = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='aliases')
    alts     = models.JSONField(default=list)
    note     = models.CharField(max_length=200, blank=True)
```

> `torch_model_index` (121) chỉ là danh sách model_code — **không cần model riêng**, đã suy ra được từ `Torch`. Seed bỏ qua, hoặc dùng để validate sau khi nạp Torch.

> Quyết định lưu dạng quan hệ (không phải JSONField gộp): vì bot **query** các nhóm này (lọc negative rule khi gợi ý, tìm set upsell theo current_class). Quan hệ cho phép index + join nhanh; JSONField sẽ phải scan.

---

## 4. App crm

```python
class Customer(BaseModel, SoftDeleteMixin):
    code     = models.CharField(max_length=20, unique=True)   # 'KH-0012'
    name     = models.CharField(max_length=200)
    tax_code = models.CharField(max_length=20, blank=True)
    segment  = models.CharField(max_length=30, choices=[
        ('factory','Nhà máy SX'), ('integrator','Robot Integrator'),
        ('dealer','Đại lý'), ('oem','OEM'), ('shipyard','Đóng tàu')], db_index=True)
    region   = models.CharField(max_length=30, blank=True)
    address  = models.TextField(blank=True)
    status   = models.CharField(max_length=20, choices=[
        ('new','Mới'), ('potential','Tiềm năng'), ('vip','VIP'),
        ('normal','Bình thường'), ('inactive','Không hoạt động')], default='new', db_index=True)
    owner    = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='owned_customers')

class Contact(BaseModel):
    customer  = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='contacts')
    full_name = models.CharField(max_length=100)
    role      = models.CharField(max_length=50, blank=True)
    phone     = models.CharField(max_length=20, blank=True)
    email     = models.EmailField(blank=True)
    preferred_channel = models.CharField(max_length=20, default='zalo')

class Lead(BaseModel):
    company_name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=100, blank=True)
    phone        = models.CharField(max_length=20, blank=True)
    source       = models.CharField(max_length=30, choices=[
        ('zalo','Zalo'),('website','Website'),('fb','Facebook'),
        ('fair','Hội chợ'),('ads','Google Ads'),('referral','Giới thiệu')])
    interested_product = models.CharField(max_length=100, blank=True)
    score        = models.IntegerField(default=0)            # forecast_worker cập nhật
    status       = models.CharField(max_length=20, choices=[
        ('new','Mới'),('processing','Đang xử lý'),
        ('qualified','Qualified'),('rejected','Loại')], default='new', db_index=True)
    notes        = models.TextField(blank=True)
    owner        = models.ForeignKey('accounts.User', on_delete=models.PROTECT, null=True, related_name='owned_leads')
    converted_opportunity = models.OneToOneField('Opportunity', null=True, blank=True,
                                on_delete=models.SET_NULL, related_name='source_lead')

class Opportunity(BaseModel):
    name        = models.CharField(max_length=200)
    customer    = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='opportunities')
    product_summary = models.CharField(max_length=200, blank=True)
    value_vnd   = models.DecimalField(max_digits=14, decimal_places=0)
    probability = models.IntegerField(default=50)
    competitor  = models.CharField(max_length=200, blank=True)
    expected_close_date = models.DateField(null=True)
    stage       = models.CharField(max_length=20, choices=[
        ('contact','Tiếp cận'),('proposal','Đề xuất'),('negotiate','Đàm phán'),
        ('won','Chốt'),('lost','Mất')], default='contact', db_index=True)
    owner       = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='owned_opportunities')

class Quote(BaseModel):
    code        = models.CharField(max_length=20, unique=True)   # 'BG-2024-088'
    customer    = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='quotes')
    opportunity = models.ForeignKey(Opportunity, null=True, blank=True, on_delete=models.SET_NULL, related_name='quotes')
    due_date    = models.DateField()
    total_vnd   = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    status      = models.CharField(max_length=20, choices=[
        ('draft','Nháp'),('sent','Đã gửi'),('pending','Chờ duyệt'),
        ('approved','Đã duyệt'),('rejected','Từ chối'),('converted','Đã chuyển HĐ')], default='draft', db_index=True)
    converted_order = models.ForeignKey('sales.SalesOrder', null=True, blank=True, on_delete=models.SET_NULL, related_name='source_quotes')
    notes       = models.TextField(blank=True)

class QuoteLine(models.Model):
    quote       = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name='lines')
    part        = models.ForeignKey('catalog.Part', null=True, on_delete=models.PROTECT)
    torch       = models.ForeignKey('catalog.Torch', null=True, on_delete=models.PROTECT)
    description = models.CharField(max_length=200)
    qty         = models.IntegerField()
    unit_price  = models.DecimalField(max_digits=14, decimal_places=0)
    discount_pct= models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total  = models.DecimalField(max_digits=14, decimal_places=0)
    order_idx   = models.IntegerField(default=0)

# + Visit, Activity, ServiceTicket, Warranty, InstalledMachine
#   (giữ nguyên như V6.A — xem skeleton tương tự; Visit có FileObject photos)
class InstalledMachine(BaseModel):
    customer   = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='installed_machines')
    torch      = models.ForeignKey('catalog.Torch', on_delete=models.PROTECT)
    serial     = models.ForeignKey('wms.SerialNumber', null=True, on_delete=models.SET_NULL)
    installed_at = models.DateField(null=True)
    warranty_until = models.DateField(null=True)
```

---

## 5. App sales (gộp 4B.4)

```python
class SalesOrder(BaseModel, SoftDeleteMixin):
    code        = models.CharField(max_length=20, unique=True)   # 'HD-2024-045'
    customer    = models.ForeignKey('crm.Customer', on_delete=models.PROTECT, related_name='orders')
    order_type  = models.CharField(max_length=20, choices=[
        ('one_off','Đơn bán'),('framework','Hợp đồng khung')], default='one_off', db_index=True)
    parent_order= models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='child_orders')
    issued_date = models.DateField()
    valid_from  = models.DateField(null=True)
    valid_to    = models.DateField(null=True)
    total_vnd   = models.DecimalField(max_digits=14, decimal_places=0)
    paid_vnd    = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    payment_terms = models.CharField(max_length=40, choices=[
        ('full_on_delivery','100% khi giao'),('half_advance','50% tạm ứng – 50% khi giao'),
        ('net_30','Công nợ 30 ngày'),('net_60','Công nợ 60 ngày')], default='full_on_delivery')
    status      = models.CharField(max_length=20, choices=[
        ('draft','Nháp'),('pending','Chờ ký'),('active','Hiệu lực'),
        ('shipping','Đang giao'),('completed','Hoàn tất'),('cancelled','Hủy')], default='draft', db_index=True)
    owner       = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='owned_orders')

class SalesOrderLine(models.Model):
    order       = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='lines')
    part        = models.ForeignKey('catalog.Part', null=True, on_delete=models.PROTECT)
    torch       = models.ForeignKey('catalog.Torch', null=True, on_delete=models.PROTECT)
    description = models.CharField(max_length=200)
    qty         = models.IntegerField()
    unit_price  = models.DecimalField(max_digits=14, decimal_places=0)
    discount_pct= models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total  = models.DecimalField(max_digits=14, decimal_places=0)
    shipped_qty = models.IntegerField(default=0)
    order_idx   = models.IntegerField(default=0)

class Payment(BaseModel):
    order      = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name='payments')
    amount_vnd = models.DecimalField(max_digits=14, decimal_places=0)
    paid_at    = models.DateField()
    method     = models.CharField(max_length=30, choices=[
        ('transfer','Chuyển khoản'),('cash','Tiền mặt'),('other','Khác')])
    reference  = models.CharField(max_length=100, blank=True)
    notes      = models.TextField(blank=True)
```

**Không có bảng `debt` riêng** — công nợ là derived: `total_vnd - paid_vnd` cho order `status in (active, shipping, completed)`, aging từ `issued_date + payment_terms`. Tổng hợp ở `mv_debt_aging` (§7).

---

## 6. App wms (multi-warehouse từ đầu)

```python
class Warehouse(BaseModel):
    code    = models.CharField(max_length=10, unique=True)   # 'HCM','HN','DN'
    name    = models.CharField(max_length=100)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

class Zone(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='zones')
    code      = models.CharField(max_length=10)
    name      = models.CharField(max_length=100)
    purpose   = models.CharField(max_length=100, blank=True)
    class Meta: unique_together = [('warehouse','code')]

class Bin(models.Model):
    zone      = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='bins')
    rack      = models.CharField(max_length=10)
    bin_code  = models.CharField(max_length=10)
    capacity  = models.IntegerField(null=True)
    full_code = models.CharField(max_length=30, unique=True, db_index=True)  # 'A-R01-B03'
    class Meta: unique_together = [('zone','rack','bin_code')]

class InventoryItem(models.Model):
    bin         = models.ForeignKey(Bin, on_delete=models.PROTECT, related_name='items')
    part        = models.ForeignKey('catalog.Part', null=True, on_delete=models.PROTECT, related_name='inventory')
    torch       = models.ForeignKey('catalog.Torch', null=True, on_delete=models.PROTECT, related_name='inventory')
    qty_on_hand = models.IntegerField(default=0)
    qty_reserved= models.IntegerField(default=0)
    min_level   = models.IntegerField(default=0)
    updated_at  = models.DateTimeField(auto_now=True)
    class Meta:
        unique_together = [('bin','part'), ('bin','torch')]
        constraints = [
            # đúng một trong hai (part XOR torch) phải not-null
            models.CheckConstraint(
                check=(models.Q(part__isnull=False, torch__isnull=True) |
                       models.Q(part__isnull=True,  torch__isnull=False)),
                name='inv_part_xor_torch'),
            models.CheckConstraint(check=models.Q(qty_on_hand__gte=0), name='inv_qty_nonneg'),
            models.CheckConstraint(check=models.Q(qty_reserved__lte=models.F('qty_on_hand')), name='inv_reserved_le_onhand'),
        ]
# Lưu ý multi-warehouse: warehouse suy ra qua bin→zone→warehouse. Mọi API
# WMS nhận/lọc theo warehouse_id (B.3) — không hardcode HCM.

class SerialNumber(BaseModel, SoftDeleteMixin):
    serial = models.CharField(max_length=40, unique=True, db_index=True)
    torch  = models.ForeignKey('catalog.Torch', on_delete=models.PROTECT, related_name='serials')
    bin    = models.ForeignKey(Bin, null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=[
        ('in_stock','Trong kho'),('reserved','Đã giữ'),('shipped','Đã giao'),
        ('sold','Đã bán'),('returned','Trả lại'),('scrapped','Hủy')], default='in_stock', db_index=True)
    sold_to_customer = models.ForeignKey('crm.Customer', null=True, blank=True, on_delete=models.PROTECT, related_name='owned_serials')
    sold_order  = models.ForeignKey('sales.SalesOrder', null=True, blank=True, on_delete=models.PROTECT, related_name='shipped_serials')
    received_at = models.DateTimeField(null=True)

class Lot(models.Model):
    lot_no       = models.CharField(max_length=40, unique=True, db_index=True)
    part         = models.ForeignKey('catalog.Part', on_delete=models.PROTECT, related_name='lots')
    qty_remaining= models.IntegerField()
    received_date= models.DateField()
    expires_at   = models.DateField(null=True)
    bin          = models.ForeignKey(Bin, null=True, on_delete=models.SET_NULL)

# ASN, InboundOrder, InboundLine, OutboundOrder, PickList, StockMovement
# — giữ nguyên skeleton V6.A. OutboundOrder.rule ∈ {FIFO,FEFO,NEAREST}.
class StockMovement(models.Model):
    """Append-only domain log của tồn kho."""
    id       = models.BigAutoField(primary_key=True)
    ts       = models.DateTimeField(auto_now_add=True, db_index=True)
    part     = models.ForeignKey('catalog.Part', null=True, on_delete=models.PROTECT)
    torch    = models.ForeignKey('catalog.Torch', null=True, on_delete=models.PROTECT)
    bin      = models.ForeignKey(Bin, on_delete=models.PROTECT)
    delta    = models.IntegerField()
    reason   = models.CharField(max_length=30)    # inbound/outbound/adjust/transfer
    ref_kind = models.CharField(max_length=20, blank=True)
    ref_id   = models.CharField(max_length=40, blank=True)
    by_user  = models.ForeignKey('accounts.User', null=True, on_delete=models.PROTECT)
    class Meta:
        indexes = [models.Index(fields=['part','-ts']), models.Index(fields=['bin','-ts'])]
```

---

## 7. App analytics — Materialized views (không model)

Raw SQL migration tạo view; **cron `refresh_mv`** (B.1 §6) REFRESH CONCURRENTLY.

| View | Group (cron) | Nội dung |
| --- | --- | --- |
| mv_monthly_revenue | hourly | revenue theo tháng × product_line × segment × region |
| mv_debt_aging | hourly | per order: due, days_overdue, bucket |
| mv_top_customers | hourly | sum YTD per customer; health |
| mv_inventory_value | hourly | qty_on_hand × price per warehouse/zone |
| mv_pipeline_forecast | hourly | value × probability per stage/owner |
| mv_installed_base | daily | InstalledMachine × torch_family; consumable demand (join **ConsumableSet**) |

```sql
CREATE MATERIALIZED VIEW mv_debt_aging AS
SELECT o.id AS order_id, o.code, o.customer_id,
       (o.total_vnd - o.paid_vnd) AS amount_due, o.issued_date,
       CASE o.payment_terms WHEN 'net_30' THEN o.issued_date + INTERVAL '30 days'
                            WHEN 'net_60' THEN o.issued_date + INTERVAL '60 days'
                            ELSE o.issued_date END AS due_date,
       GREATEST(0, CURRENT_DATE - (CASE o.payment_terms
            WHEN 'net_30' THEN o.issued_date + INTERVAL '30 days'
            WHEN 'net_60' THEN o.issued_date + INTERVAL '60 days'
            ELSE o.issued_date END)::date) AS days_overdue
FROM sales_salesorder o
WHERE o.status IN ('active','shipping','completed')
  AND o.total_vnd > o.paid_vnd AND o.deleted_at IS NULL;
CREATE UNIQUE INDEX ON mv_debt_aging (order_id);
CREATE INDEX ON mv_debt_aging (customer_id, days_overdue);
```

```python
# apps/analytics/management/commands/refresh_mv.py  (gọi bởi cron)
HOURLY = ['mv_monthly_revenue','mv_debt_aging','mv_top_customers','mv_inventory_value','mv_pipeline_forecast']
DAILY  = ['mv_installed_base']
# manage.py refresh_mv --group=hourly|daily → REFRESH MATERIALIZED VIEW CONCURRENTLY ...
```

---

## 8. App storage — FileObject (MinIO từ đầu)

```python
class FileObject(BaseModel):
    kind        = models.CharField(max_length=30, db_index=True)   # visit_photo/ticket_attach/vision/avatar
    filename    = models.CharField(max_length=255)
    mime_type   = models.CharField(max_length=80)
    size_bytes  = models.BigIntegerField()
    backend     = models.CharField(max_length=20, default='s3')    # MinIO từ đầu (đổi từ 'local')
    bucket      = models.CharField(max_length=63, default='tokinarc')
    path        = models.CharField(max_length=500)                 # S3 key
    sha256      = models.CharField(max_length=64, db_index=True)   # dedup
    related_kind= models.CharField(max_length=40, blank=True)
    related_id  = models.CharField(max_length=64, blank=True)
```

`apps/storage/services.py::save_upload(file, kind=..., related=...)` dùng `minio`/`boto3`, caller không quan tâm backend. Cấu hình MinIO endpoint/key qua env (B.5 §4).

---

## 9. App learning — Query log, Critic, Golden Store (vòng học)

Hỗ trợ vòng học offline (chi tiết pipeline ở B.5 §2). Đây là phần **store**; logic chạy ở cron + sidecar.

```python
# apps/learning/models.py
class QueryLog(models.Model):
    """Sidecar ghi mỗi truy vấn chat (cũng append vào queries.jsonl để batch)."""
    id            = models.BigAutoField(primary_key=True)
    ts            = models.DateTimeField(auto_now_add=True, db_index=True)
    session_id    = models.CharField(max_length=64, db_index=True)
    role          = models.CharField(max_length=20)            # customer/sales/...
    query_text    = models.TextField()
    planner_tools = models.JSONField(default=list)             # tool Planner chọn
    response_text = models.TextField(blank=True)
    confidence    = models.DecimalField(max_digits=4, decimal_places=3, null=True)
    conf_tier     = models.CharField(max_length=10, blank=True)  # high/med/low
    latency_ms    = models.IntegerField(null=True)
    critic_score  = models.IntegerField(null=True, db_index=True)  # 1..5, do Critic batch điền
    critic_note   = models.TextField(blank=True)
    promoted      = models.BooleanField(default=False, db_index=True)

class GoldenExample(models.Model):
    """Few-shot đã duyệt — bơm ngược về Planner."""
    id          = models.BigAutoField(primary_key=True)
    source_log  = models.ForeignKey(QueryLog, null=True, on_delete=models.SET_NULL)
    query_text  = models.TextField()
    ideal_tools = models.JSONField(default=list)
    ideal_answer= models.TextField()
    tags        = models.JSONField(default=list)               # ['compatibility','upsell']
    score       = models.IntegerField()                        # ≥4
    confidence  = models.DecimalField(max_digits=4, decimal_places=3)  # ≥0.85
    active      = models.BooleanField(default=True, db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True)

class EventDeadLetter(models.Model):
    """Bù retry cho LISTEN/NOTIFY (B.1 §5.4)."""
    id      = models.BigAutoField(primary_key=True)
    channel = models.CharField(max_length=40, db_index=True)
    payload = models.JSONField()
    error   = models.TextField()
    ts      = models.DateTimeField(auto_now_add=True)
    retries = models.IntegerField(default=0)
    resolved= models.BooleanField(default=False, db_index=True)
```

---

## 10. Indexes, constraints, performance

**Index bắt buộc** (ngoài Meta đã khai):
- AuditLog `(entity, entity_id, -ts)`; SalesOrder `(customer_id, status, -issued_date)`.
- InventoryItem partial `WHERE qty_on_hand <= min_level` (query "sắp hết").
- PartEmbedding HNSW cosine (đã khai).
- StockMovement `(part_id, -ts)`, `(bin_id, -ts)`.
- ProcessEdge `(to_process, is_preferred)`; NegativeRule `(from_category, to_category)` (bot lọc nhanh).
- QueryLog `(critic_score)`, `(promoted)`; GoldenExample `(active)`.

**Constraint bắt buộc**:
- `Quote.total_vnd` = sum lines (signal `post_save` QuoteLine).
- `SalesOrder.paid_vnd <= total_vnd` (CHECK).
- InventoryItem: part XOR torch, qty≥0, reserved≤on_hand (đã khai §6).
- `SalesOrderLine.shipped_qty <= qty` (CHECK).

**Concurrency**:
- Giữ serial khi convert quote→order: `SELECT ... FOR UPDATE`, check `status='in_stock'` → `reserved`.
- Stock adjust: `F('qty_on_hand') + delta` tránh race.

---

## 11. Migration & seed strategy

| Bước | Lệnh |
| --- | --- |
| 1. Schema | `python manage.py makemigrations && migrate` |
| 2. pgvector ext | migration tay `CREATE EXTENSION IF NOT EXISTS vector;` (trong `0001` của catalog) |
| 3. Materialized views | raw SQL migration trong apps/analytics |
| 4. Seed catalog **12 nhóm** | `python manage.py seed_from_json data/tokinarc_data_v19.json` — **nạp đủ cả 5 nhóm bổ sung** |
| 5. Seed embeddings | `python manage.py seed_embeddings` (BGE-M3, bulk; chia batch nếu lâu) |
| 6. Seed users/roles | `python manage.py seed_users_roles --admin-email=...` |
| 7. (dev/staging) demo | `python manage.py seed_demo_data` |

`seed_from_json` phải xử lý đúng thứ tự FK: Torch, Part trước → rồi CompatibilityEdge, TorchPartMapping, ProcessEdge, GasFlowEdge, ConsumableSet(+Item), NegativeRule, CategoryVocabulary, PartNoAlias. Wrapper `scripts/run_migrations.sh` gọi tuần tự. Giữ JSON v19 làm nguồn chuẩn, không sửa trực tiếp DB cho catalog.
