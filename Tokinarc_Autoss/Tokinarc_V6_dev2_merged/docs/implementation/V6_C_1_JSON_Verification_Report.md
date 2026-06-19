# Tokinarc V6.C.1 — JSON Data Verification Report

**File**: `tokinarc_data_v19.json` (3.46 MB)
**Verified at**: 2026-06-16
**Verdict**: ✅ Data integrity good · 🔴 Seed script has 9 bugs (will crash or silently drop data)

## TL;DR

| Khía cạnh | Kết quả |
| --- | --- |
| Counts top-level | 12 nhóm, 837 parts, 121 torches, 7541 edges, 1518 TPM |
| Duplicate PK | 0 (cả torches + parts) |
| Orphan cross-references | **0** (đã check toàn bộ FK ngầm) |
| Schema consistency | 🟡 Có shape variants trong nhiều nhóm (xem §3) |
| meta.stats drift | 🟡 3/4 con số sai (xem §1) |
| seed_from_json.py compatibility | 🔴 9 lỗi field name (xem §4) |
| Schema richness | 🟡 Model V6.A.2 captures ~30% số field thực có |

Kết luận: data hoàn toàn dùng được — không cần làm sạch. Nhưng **seed script và models.py phải viết lại** để khớp shape thực tế.

## 1. Stats drift (meta vs reality)

`meta.stats` đã không được cập nhật sau các patch v18, v19:

| Stat | Declared | Actual | Drift |
| --- | --- | --- | --- |
| torch_count | 121 | 121 | ✓ |
| part_count | 838 | 837 | -1 |
| compatibility_edge_count | 7588 | 7541 | -47 |
| tpm_count | 1517 | 1518 | +1 |

Không nghiêm trọng — chỉ cần nhớ rằng `meta.stats` là indicative, **không bao giờ dùng nó làm nguồn chuẩn**. Khi seed, đếm `len()` trực tiếp.

## 2. Data integrity (cross-reference)

Kiểm tra toàn bộ FK ngầm (part_no, torch_model) qua mọi nhóm:

| Check | Số orphan |
| --- | --- |
| TPM `part_nos[]` không tồn tại trong parts | 0 |
| TPM `torch_model` không tồn tại trong torches | 0 |
| process_edges `from_part` orphan | 0 |
| gas_flow_edges `from_orifice` / `to_nozzle` orphan | 0 |
| consumable_sets items `part_id` / `part_no` orphan | 0 |
| fake_pno_aliases `primary` orphan | 0 |
| compatibility_edges `from_part` / `to_part` orphan | 0 |
| torch_model_index entries không có trong torches | 0 |

**100% sạch** — không có rác data.

## 3. Schema variants (cùng nhóm, nhiều shape)

Đây là nguyên nhân chính khiến seed script không thể "1 shape fits all". Khi seed phải **normalize**:

### 3.1 compatibility_edges — 5 shape

| Shape (keys) | Count |
| --- | --- |
| `from_part, to_part, relation_type, priority_rank, is_mandatory, source, confidence` | 7488 |
| `from, to, relation, weight` (cũ — dùng `from/to` thay vì `from_part/to_part`) | 22 |
| Có thêm `note` | 16 |
| Minimal shape không có source/confidence | 13 |
| Có `result_part` (cạnh "kết quả" — assembly chain) | 2 |

Normalize tại seed: 22 entries dùng `from/to/relation/weight` → ánh xạ sang `from_part/to_part/relation_type/confidence`. Tất cả còn lại fill default.

### 3.2 torch_part_mappings — 5 shape

| Shape | Count |
| --- | --- |
| `torch_model, ref_no, part_nos, part_role, is_mandatory, source` | 589 |
| Có thêm `confidence + note` | 452 |
| Có thêm `confidence` (không note) | 343 |
| Có `note` (không confidence) | 70 |
| Có cả `robot_model + wire_size_applicability` | 36 |

**Quan trọng**: TPM lưu `part_nos` là **array**, không phải 1 part_no. 1518 TPM rows → 2921 (torch, part, role) tuples sau khi explode. Seed phải explode.

### 3.3 consumable_sets — 2 shape

- 15/20 sets dùng key `items`: items có `part_id, priority_rank, is_mandatory, default_quantity, note, part_role`
- 8/20 sets dùng key `parts`: items có `part_no, role, note` (không quantity, không priority)

Normalize tại seed: thử cả 2 key, ưu tiên `items` nếu có cả hai.

### 3.4 negative_rules — 30+ field

17 rules nhưng có 30 field xuất hiện ít nhất 1 lần (applicable_tips, exception_torch_models, exclusive_nozzle, requires, ...). Model nên có cột chính + JSONField `extras` cho field hiếm.

## 4. seed_from_json.py — 9 lỗi cần sửa

Bảng dưới ánh xạ **mã lỗi → vị trí trong file artifact gửi lên → hệ quả**:

| # | Line | Đọc | Thực tế | Hệ quả |
| --- | --- | --- | --- | --- |
| 1 | 79 | `r.get("display_name", r["model_code"])` | JSON có `display_name_vi` (121/121) | Tên hiển thị torch = model_code, mất nội dung tiếng Việt cho cả 121 torch |
| 2 | 107 | `r.get("price_vnd")` (top-level) | JSON có `r["business"]["price_vnd"]` (837/837) | **Mất 100% giá parts** |
| 3 | (torch) | Không đọc business | torch cũng có `business` (121/121) | **Mất 100% giá torch** |
| 4 | 134 | `r["src"]`, `r["src_kind"]`, `r["dst"]`, `r["dst_kind"]`, `r["edge_type"]` | JSON dùng `from_part, to_part, relation_type` | **KeyError trên dòng đầu tiên — seed crash ngay** |
| 5 | 142 | `r["torch"]`, `r["part"]`, `r.get("role")` | JSON dùng `torch_model`, `part_nos` (array!), `part_role` | **KeyError — crash** |
| 6 | 174–190 | `s["items"]` only | 8/20 sets dùng key `parts` thay vì `items` | 40% consumable sets bị skip |
| 7 | 184 | `item.get("part")` | JSON có `part_id` (items) hoặc `part_no` (parts) | Tất cả ConsumableSetItem bị skip do check filter `Part.objects.filter(pk=pno)` với `pno=None` |
| 8 | 189–190 | `item.get("qty", 1)`, `item.get("role", "")` | JSON có `default_quantity`, `part_role` | Mọi quantity = 1, mọi role = "" |
| 9 | 193 | Bỏ qua 25 field rare của negative_rules | JSON có applicable_tips, exception_torch_models, exclusive_nozzle, requires... | Logic phủ định chỉ giữ ~20% thông tin |

**Bug số 4 và 5 chặn cứng** — seed sẽ crash trước cả khi seed được 1 row compatibility edge hay TPM.

## 5. Schema richness — V6.A.2 model thiếu rất nhiều

So sánh nhanh:

| Entity | Số key xuất hiện trong JSON | V6.A.2 capture | % giữ |
| --- | --- | --- | --- |
| Torch | ~60 | ~9 | 15% |
| Part | ~97 | ~20 | 21% |
| NegativeRule | ~30 | 7 | 23% |
| ConsumableSet | 17 | 8 | 47% |

Mất nhiều field quan trọng cho LLM/chatbot:

**Torch — field quan trọng đang mất**:
- `family` (TK, TA, ACC, CSL, …) — để gộp torch theo dòng
- `cooling` (air/water) — query rất thường xuyên
- `rated_dc_a / rated_co2_a / rated_mag_a / rated_mig_a` — câu hỏi capacity
- `duty_cycle_pct` — tham số kỹ thuật then chốt
- `wire_size` — cỡ dây tương thích
- `mounting`, `connection_types` — chọn adapter
- `has_shock_sensor`, `shock_sensor_type` — feature bít
- `weight_g`, `body_length`, `cable_length_m` — spec vật lý
- `editorial_picks` — gợi ý của chuyên gia (đắt nếu mất)
- `tpm_count`, `compatible_parts` — denormalized refs (giúp query nhanh)

**Part — field quan trọng đang mất**:
- `supported_processes` (CO2/MAG/...)
- `tip_type` (N/D/O)
- `wire_material` (steel/stainless)
- `p_model_codes, d_model_codes, o_model_codes` (cross-vendor torch refs)
- `applicable_torches`, `compatible_with` (denormalized)
- `editorial_picks`
- Mọi field category-specific: `body_dia_mm`, `bore_dia_mm`, `for_gas_lens`, `electrode_dia_mm`, v.v.

## 6. Cấu trúc business (pricing) — phải flatten hoặc nested?

Pricing được đặt trong sub-object `business`:

```json
"business": {
  "price_vnd": 18000,
  "price_unit": "cái",
  "price_note": "",
  "is_contact_price": false,
  "is_priority_sell": false,
  "price_updated": "2026-05",
  "price_tier": "mock_v1"
}
```

**Khuyến nghị**: Flatten các field vào cột (price_vnd, price_unit, ...) để filter SQL nhanh:
- "Filter part theo price range" — cần index B-tree, không làm được trên JSONB.
- "Filter is_priority_sell=true" — cần partial index.

Đánh đổi: khi sửa giá phải update 7 cột thay vì 1 JSON field. OK vì giá ít thay đổi.

## 7. Khuyến nghị tổng

| Hành động | Ưu tiên |
| --- | --- |
| **Viết lại `models.py`** để match shape thực (xem V6.C.2) | 🔴 |
| **Viết lại `seed_from_json.py`** đúng tên field + explode TPM + normalize variants (xem V6.C.3) | 🔴 |
| Bổ sung `JSONField specs` cho Torch & Part để chứa các field category-specific không promote thành cột | 🟠 |
| Flatten `business.*` vào cột Part/Torch | 🟠 |
| Đồng bộ `meta.stats` (có thể không cần — chỉ ghi log warning) | 🟢 |
| Thêm validator cho category vs `category_vocabulary` (cảnh báo nếu category lạ) | 🟢 |
| Tách `compatible_parts/compatible_with/used_with/editorial_picks` thành derived view (materialized) thay vì lưu trên row | 🟢 (tương lai) |
