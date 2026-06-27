"""
Tokinarc V6.C — apps/catalog/models.py

Phiên bản đã được chốt sau khi verify tokinarc_data_v19.json (V6.C.1).
Khác V6.A.2 ở các điểm chính:

  1. Torch.display_name_vi + display_name_en thay vì display_name singular
     (JSON dùng vi/en, không có 'display_name').
  2. Pricing flatten từ sub-object `business` thành cột riêng (cả Torch & Part).
  3. Thêm JSONField `specs` để chứa field category-specific không promote
     thành cột — tránh mất ~70-80% nội dung JSON.
  4. CompatibilityEdge schema theo JSON thực: from_part / to_part / relation_type
     (không phải src/dst/edge_type như V6.A.2 ban đầu).
  5. TorchPartMapping được explode tại seed time: 1 row = 1 (torch, part, role)
     thay vì lưu nested array.
  6. NegativeRule có JSONField `extras` chứa 25 field rare.
  7. Cross-references dùng CharField loose key (db_index) thay vì ForeignKey —
     tránh phụ thuộc seed order, dễ chạy lại từng phần. Đã verify zero orphan
     trong V6.C.1 nên không mất gì về toàn vẹn.
  8. Thêm SeedMeta để audit version JSON đã seed.

Mọi model dùng explicit `db_table` (catalog_*) — phòng case Django settings
thiếu `default_app_config`.
"""
from django.db import models
from pgvector.django import HnswIndex, VectorField


# ─── Torch ───────────────────────────────────────────────────────────────────
class Torch(models.Model):
    """Súng hàn / torch (model_code làm PK)."""

    model_code      = models.CharField(max_length=40, primary_key=True)
    display_name_vi = models.CharField(max_length=200)
    display_name_en = models.CharField(max_length=200, blank=True)

    # Phân loại chính (query rất thường xuyên)
    family          = models.CharField(max_length=20, blank=True, db_index=True)
    ecosystem       = models.CharField(max_length=10, db_index=True)
    current_class   = models.CharField(max_length=20, db_index=True)
    body_type       = models.CharField(max_length=20, blank=True)   # 'RR', 'MAH', 'CSL', ...
    cooling         = models.CharField(max_length=20, blank=True, db_index=True)  # 'air' / 'water'

    # Process / wire
    process         = models.JSONField(default=list)          # ['CO2', 'MAG', 'MIG', 'TIG']
    welding_process = models.JSONField(default=list)          # alternative naming trong JSON
    wire_size       = models.CharField(max_length=40, blank=True)  # '0.8-1.2mm'

    # Spec promoted columns (query nhiều)
    rated_dc_a       = models.IntegerField(null=True, blank=True)
    rated_co2_a      = models.IntegerField(null=True, blank=True)
    rated_mag_a      = models.IntegerField(null=True, blank=True)
    rated_mig_a      = models.IntegerField(null=True, blank=True)
    duty_cycle_pct   = models.IntegerField(null=True, blank=True)
    duty_co2_pct     = models.IntegerField(null=True, blank=True)
    duty_mag_pct     = models.IntegerField(null=True, blank=True)
    weight_g         = models.IntegerField(null=True, blank=True)

    # Feature flags
    has_shock_sensor   = models.BooleanField(default=False)
    shock_sensor_type  = models.CharField(max_length=40, blank=True)
    has_cylinder       = models.BooleanField(default=False)
    has_air_cylinder   = models.BooleanField(default=False)
    is_detachable      = models.BooleanField(default=False)
    is_ultralight      = models.BooleanField(default=False)

    # Mounting / connection
    mounting          = models.CharField(max_length=20, blank=True)
    connection_types  = models.JSONField(default=list)
    connector_type    = models.CharField(max_length=40, blank=True)

    # Denormalized refs (giúp query nhanh, không cần JOIN)
    compatible_parts  = models.JSONField(default=list)
    editorial_picks   = models.JSONField(default=list)
    tpm_count         = models.IntegerField(default=0)

    # Pricing (flatten từ business)
    price_vnd         = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    # Giá vốn bình quân gia quyền (WAC) — NHẠY CẢM, chỉ manager+ xem. Tự cập nhật khi nhập kho.
    cost_vnd          = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    price_unit        = models.CharField(max_length=10, default='cái')
    price_note        = models.TextField(blank=True)
    is_contact_price  = models.BooleanField(default=False)
    is_priority_sell  = models.BooleanField(default=False, db_index=True)
    price_updated     = models.CharField(max_length=10, blank=True)
    price_tier        = models.CharField(max_length=20, blank=True)

    # Catch-all (chứa 40+ field hiếm như robot_compatibility, tig_family, ...)
    specs             = models.JSONField(default=dict)
    notes             = models.TextField(blank=True)
    source            = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'catalog_torch'
        indexes  = [
            models.Index(fields=['ecosystem', 'current_class', 'cooling'], name='cat_torch_eco_cur_cool_idx'),
            models.Index(fields=['family', 'current_class'], name='cat_torch_fam_cur_idx'),
            models.Index(fields=['body_type', 'cooling'], name='cat_torch_body_cool_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.model_code} — {self.display_name_vi}"


# ─── Part ────────────────────────────────────────────────────────────────────
class Part(models.Model):
    """Phụ kiện / consumable (tokin_part_no làm PK)."""

    tokin_part_no   = models.CharField(max_length=40, primary_key=True)
    category        = models.CharField(max_length=40, db_index=True)
    ecosystem       = models.CharField(max_length=10, blank=True, db_index=True)
    current_class   = models.CharField(max_length=20, blank=True, db_index=True)

    display_name_vi = models.CharField(max_length=200)
    display_name_en = models.CharField(max_length=200, blank=True)

    # Barcode/QR nhà SX (EAN-13 / mã Tokin trên tem) → map về part_no nội bộ.
    # Học dần bằng "quét-gán": lần đầu quét tem lạ → gán cho 1 part → lưu vĩnh viễn.
    barcode         = models.CharField(max_length=64, blank=True, db_index=True)

    # Spec promoted
    wire_size_mm    = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    total_length_mm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    body_length_mm  = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    thread_type     = models.CharField(max_length=30, blank=True)
    material        = models.CharField(max_length=40, blank=True)
    tip_type        = models.CharField(max_length=20, blank=True)
    wire_material   = models.CharField(max_length=40, blank=True)
    supported_processes = models.JSONField(default=list)

    # Cross-vendor aliases
    p_part_nos      = models.JSONField(default=list)
    d_part_nos      = models.JSONField(default=list)
    o_part_nos      = models.JSONField(default=list)
    p_model_codes   = models.JSONField(default=list)
    d_model_codes   = models.JSONField(default=list)
    o_model_codes   = models.JSONField(default=list)

    # Denormalized refs (giúp LLM context build nhanh không cần JOIN)
    compatible_with     = models.JSONField(default=list)
    used_with           = models.JSONField(default=list)
    torch_models        = models.JSONField(default=list)
    applicable_torches  = models.JSONField(default=list)
    editorial_picks     = models.JSONField(default=list)

    # Pricing (flatten từ business)
    price_vnd        = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    # Giá vốn bình quân (WAC) — NHẠY CẢM, chỉ manager+ xem. Tự cập nhật khi nhập kho.
    cost_vnd         = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    price_unit       = models.CharField(max_length=10, default='cái')
    price_note       = models.TextField(blank=True)
    is_contact_price = models.BooleanField(default=False)
    is_priority_sell = models.BooleanField(default=False, db_index=True)
    price_updated    = models.CharField(max_length=10, blank=True)
    price_tier       = models.CharField(max_length=20, blank=True)

    # Catch-all + provenance
    specs            = models.JSONField(default=dict)
    source           = models.CharField(max_length=200, blank=True)
    confidence       = models.DecimalField(max_digits=3, decimal_places=2, default=1)
    notes            = models.TextField(blank=True)

    class Meta:
        db_table = 'catalog_part'
        indexes  = [
            models.Index(fields=['category', 'ecosystem'], name='cat_part_cat_eco_idx'),
            models.Index(fields=['category', 'current_class'], name='cat_part_cat_cur_idx'),
            models.Index(fields=['ecosystem', 'current_class', 'category'], name='cat_part_eco_cur_cat_idx'),
            models.Index(fields=['is_priority_sell', 'category'], name='cat_part_prio_cat_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.tokin_part_no} — {self.display_name_vi}"


# ─── CompatibilityEdge ───────────────────────────────────────────────────────
class CompatibilityEdge(models.Model):
    """
    Cạnh tương thích Part↔Part hoặc Part↔Torch.
    Schema khớp JSON v19 (từ V6.C.1 verification):
      - 7488 entries dùng from_part/to_part/relation_type/priority_rank/is_mandatory/source/confidence
      - 22 entries (cũ) dùng from/to/relation/weight — seed normalize sang
        from_part/to_part/relation_type/confidence.
    """
    id            = models.BigAutoField(primary_key=True)
    from_part     = models.CharField(max_length=40, db_index=True)
    to_part       = models.CharField(max_length=40, db_index=True)
    relation_type = models.CharField(max_length=30, default='compatible_with', db_index=True)
    priority_rank = models.IntegerField(default=0)
    is_mandatory  = models.BooleanField(default=False)
    confidence    = models.DecimalField(max_digits=3, decimal_places=2, default=1)
    note          = models.CharField(max_length=300, blank=True)
    source        = models.CharField(max_length=200, blank=True)
    # Cho 2 entries dùng 'result_part' (assembly chain)
    result_part   = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = 'catalog_compatibility_edge'
        constraints = [
            models.UniqueConstraint(
                fields=['from_part', 'to_part', 'relation_type'],
                name='uniq_compat_edge_triple',
            ),
        ]
        indexes = [
            models.Index(fields=['from_part', 'relation_type', 'priority_rank'], name='cat_ce_from_rel_idx'),
            models.Index(fields=['to_part', 'relation_type'], name='cat_ce_to_rel_idx'),
        ]


# ─── TorchPartMapping (exploded) ─────────────────────────────────────────────
class TorchPartMapping(models.Model):
    """
    Một dòng = (torch_model, part_no, part_role, ref_no).
    JSON gốc lưu nested (1 TPM = 1 torch + part_nos array), seed sẽ EXPLODE:
        1518 TPM rows → 2921 (torch, part, role) tuples.
    """
    id              = models.BigAutoField(primary_key=True)
    torch_model     = models.CharField(max_length=40, db_index=True)
    part_no         = models.CharField(max_length=40, db_index=True)
    part_role       = models.CharField(max_length=40, db_index=True)
    ref_no          = models.CharField(max_length=20, blank=True)
    is_mandatory    = models.BooleanField(default=False)
    confidence      = models.DecimalField(max_digits=3, decimal_places=2, default=1)
    note            = models.CharField(max_length=300, blank=True)
    source          = models.CharField(max_length=200, blank=True)
    # Optional (chỉ 36/1518 có)
    robot_model     = models.CharField(max_length=40, blank=True)
    connection_type = models.CharField(max_length=20, blank=True)
    wire_size_applicability = models.JSONField(default=list)

    class Meta:
        db_table = 'catalog_torch_part_mapping'
        constraints = [
            models.UniqueConstraint(
                fields=['torch_model', 'part_no', 'part_role', 'ref_no'],
                name='uniq_tpm',
            ),
        ]
        indexes = [
            models.Index(fields=['torch_model', 'part_role'], name='cat_tpm_torch_role_idx'),
            models.Index(fields=['part_no'], name='cat_tpm_part_idx'),
        ]


# ─── ProcessEdge ─────────────────────────────────────────────────────────────
class ProcessEdge(models.Model):
    """Part → quy trình hàn được hỗ trợ (CO2/MAG/MIG/TIG/...)."""
    id            = models.BigAutoField(primary_key=True)
    from_part     = models.CharField(max_length=40, db_index=True)
    to_process    = models.CharField(max_length=20, db_index=True)
    relation_type = models.CharField(max_length=30, default='supports_process')
    is_preferred  = models.BooleanField(default=False)
    note          = models.CharField(max_length=300, blank=True)
    source        = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'catalog_process_edge'
        constraints = [
            models.UniqueConstraint(
                fields=['from_part', 'to_process', 'relation_type'],
                name='uniq_process_edge',
            ),
        ]


# ─── GasFlowEdge ─────────────────────────────────────────────────────────────
class GasFlowEdge(models.Model):
    """Orifice → Nozzle compatibility theo dòng khí."""
    id            = models.BigAutoField(primary_key=True)
    from_orifice  = models.CharField(max_length=40, db_index=True)
    to_nozzle     = models.CharField(max_length=40, db_index=True)
    relation_type = models.CharField(max_length=30, default='fits_in_nozzle')
    reason        = models.CharField(max_length=500, blank=True)
    source        = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'catalog_gas_flow_edge'
        constraints = [
            models.UniqueConstraint(
                fields=['from_orifice', 'to_nozzle', 'relation_type'],
                name='uniq_gas_flow_edge',
            ),
        ]


# ─── ConsumableSet + Item ────────────────────────────────────────────────────
class ConsumableSet(models.Model):
    """
    Bộ consumable hoàn chỉnh cho 1 cấu hình torch.
    JSON có 2 shape:
      - 15/20: dùng key `items` với item shape: part_id, priority_rank,
        is_mandatory, default_quantity, note, part_role
      - 8/20: dùng key `parts` với item shape: part_no, role, note
    Seed sẽ normalize cả hai về model ConsumableSetItem.
    """
    set_id              = models.CharField(max_length=60, primary_key=True)
    display_name_vi     = models.CharField(max_length=200)
    torch_current_class = models.CharField(max_length=20, blank=True)
    ecosystem           = models.CharField(max_length=10, blank=True)
    cooling_method      = models.CharField(max_length=20, blank=True)
    default_wire_size_mm= models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    torch_models        = models.JSONField(default=list)
    notes               = models.TextField(blank=True)

    class Meta:
        db_table = 'catalog_consumable_set'


class ConsumableSetItem(models.Model):
    id              = models.BigAutoField(primary_key=True)
    consumable_set  = models.ForeignKey(
        ConsumableSet, on_delete=models.CASCADE, related_name='items',
        db_column='consumable_set_id'
    )
    part_no         = models.CharField(max_length=40, db_index=True)
    part_role       = models.CharField(max_length=40, blank=True)
    priority_rank   = models.IntegerField(default=0)
    is_mandatory    = models.BooleanField(default=False)
    default_quantity= models.IntegerField(default=1)
    note            = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = 'catalog_consumable_set_item'
        constraints = [
            models.UniqueConstraint(
                fields=['consumable_set', 'part_no', 'part_role'],
                name='uniq_consumable_item',
            ),
        ]


# ─── NegativeRule ────────────────────────────────────────────────────────────
class NegativeRule(models.Model):
    """
    Quy tắc phủ định (incompatible_with, ...).
    JSON có 30+ field rare cho edge case — core fields trong cột, rare trong
    JSONField `extras`.
    """
    rule_id              = models.CharField(max_length=60, primary_key=True)
    description          = models.CharField(max_length=300)
    from_category        = models.CharField(max_length=40, blank=True)
    to_category          = models.CharField(max_length=40, blank=True)
    from_ecosystem       = models.CharField(max_length=10, blank=True)
    to_ecosystem         = models.CharField(max_length=10, blank=True)
    from_current_class   = models.CharField(max_length=20, blank=True)
    relation_type        = models.CharField(max_length=30, default='incompatible_with')
    incompatibility_reason = models.TextField(blank=True)
    confidence           = models.DecimalField(max_digits=3, decimal_places=2, default=1)
    source               = models.CharField(max_length=200, blank=True)
    # Tất cả field rare khác (applicable_tips, exception_torch_models,
    # exclusive_nozzle, requires, excluded_nozzles, from_tip_type, ...)
    extras               = models.JSONField(default=dict)

    class Meta:
        db_table = 'catalog_negative_rule'


# ─── CategoryVocabulary ──────────────────────────────────────────────────────
class CategoryVocabulary(models.Model):
    """Map en_term ↔ vi_term + aliases — phục vụ search tiếng Việt."""
    en_term       = models.CharField(max_length=60, primary_key=True)
    vi_term       = models.CharField(max_length=60)
    part_category = models.CharField(max_length=40, db_index=True)
    vi_aliases    = models.JSONField(default=list)

    class Meta:
        db_table = 'catalog_category_vocabulary'


# ─── PartNoAlias ─────────────────────────────────────────────────────────────
class PartNoAlias(models.Model):
    """
    fake_pno_aliases — typo/OCR/reverse-prefix mapping về part chính thức.
    Ví dụ: '005001' (typo) → primary '001005'.
    """
    fake_pno = models.CharField(max_length=40, primary_key=True)
    primary  = models.CharField(max_length=40, db_index=True)
    alts     = models.JSONField(default=list)
    note     = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = 'catalog_part_no_alias'


# ─── PartEmbedding ───────────────────────────────────────────────────────────
class PartEmbedding(models.Model):
    """BGE-M3 embedding cho semantic search qua pgvector."""
    part_no    = models.CharField(max_length=40, primary_key=True)
    text_hash  = models.CharField(max_length=64, db_index=True)
    vector     = VectorField(dimensions=1024)
    model_ver  = models.CharField(max_length=40, default='BAAI/bge-m3')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'catalog_part_embedding'
        indexes  = [
            HnswIndex(
                name='part_emb_hnsw',
                fields=['vector'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops'],
            ),
        ]


# ─── ProcedureQA — tra cứu lắp đặt / sửa chữa nội bộ ──────────────────────────
class ProcedureQA(models.Model):
    """Hỏi-đáp lắp đặt / sửa chữa / tra cứu — migrate từ chatbot procedural_qa_kb.
    Cho nhân sự nội bộ (kỹ sư dịch vụ, kho) tra cứu quy trình + cách xử lý lỗi."""
    KIND = [
        ('INSTALLATION', 'Lắp đặt'),
        ('REPAIR', 'Sửa chữa'),
        ('LOOKUP', 'Tra cứu'),
    ]
    intent   = models.CharField(max_length=20, choices=KIND, db_index=True)
    question = models.CharField(max_length=400)
    answer   = models.TextField()
    source   = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'catalog_procedure_qa'
        ordering = ['intent', 'question']
        indexes = [models.Index(fields=['intent'])]

    def __str__(self) -> str:
        return f"[{self.intent}] {self.question[:60]}"


# ─── SeedMeta ────────────────────────────────────────────────────────────────
class SeedMeta(models.Model):
    """
    Singleton — lưu metadata lần seed gần nhất. Audit + dò drift sau này.
    Luôn ghi đè row id=1.
    """
    id        = models.IntegerField(primary_key=True, default=1)
    version   = models.CharField(max_length=20)
    seed_at   = models.DateTimeField(auto_now=True)
    json_meta = models.JSONField(default=dict)
    counts    = models.JSONField(default=dict)

    class Meta:
        db_table = 'catalog_seed_meta'
