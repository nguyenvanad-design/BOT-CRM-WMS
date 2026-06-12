# Ontology TOKINARC v3.0

> **Tình trạng**: Đã hiện thực hoá trong `tokinarc_schema_v11_r5.py` + `tokinarc_data_v11g.json` + `compatibility_matrix_v11g.py` + `assembly_procedures_v1_2.json`
>
> **Phiên bản tài liệu**: v3.0 (19/05/2026)
> **Catalog gốc**: CATALOG_01..05 (TOKIN Corp, ấn bản 2017-2024)
> **Duy trì bởi**: Aggeny Digital × Autoss VN
>
> **Mục đích file này**: Là **single source of truth** cho mô hình khái niệm của miền nghiệp vụ súng hàn công nghiệp TOKINARC. Mọi thứ trong 4 file code/data phải suy ra được từ tài liệu này. Nếu lệch nhau, **tài liệu này thắng** — code sai phải sửa code.

---

## 0. Tra cứu nhanh — cái gì ở file nào

| Lĩnh vực | File | Định dạng |
|----------|------|-----------|
| Định nghĩa kiểu, enum, validation | `tokinarc_schema_v11_r5.py` | Pydantic |
| Instance thực thể (torch, part) | `tokinarc_data_v11g.json` | JSON |
| Quan hệ (compatibility, process, gas-flow) | `compatibility_matrix_v11g.py` | Python list literal |
| Tri thức quy trình (lắp đặt, sửa chữa, an toàn) | `assembly_procedures_v1_2.json` | JSON |

Bốn file gộp lại tạo thành **knowledge base**. Tài liệu ontology này mô tả **hình dáng** của knowledge base đó.

---

## 1. Phạm vi nghiệp vụ

Ontology bao trùm hệ sinh thái súng hàn công nghiệp của TOKIN Corporation:

**Trong phạm vi**:
- Súng hàn MIG/MAG (semi-auto, automatic, robotic)
- Súng hàn TIG (manual, robotic, có bộ thay tungsten)
- Phụ kiện tiêu hao (béc, chụp gas, lỗ định hướng, sứ cách điện, liner, ...)
- Phụ kiện kết cấu (thân súng, ống trong, tip body)
- Thiết bị phụ trợ (cáp nguồn, bracket, mặt bích, hút khói, hệ thống nước làm mát)
- Quan hệ tương thích giữa torch, part, quá trình hàn
- Quy trình lắp đặt, thay thế và cảnh báo an toàn

**Ngoài phạm vi**:
- Nguồn hàn (chỉ nhắc đến chứ không model — là sản phẩm bên thứ ba)
- Bộ cấp dây (chỉ làm điểm kết nối — xem field `wire_feeder` trong assembly_sequences)
- Phôi và kim loại nền
- Chất lượng mối hàn (rỗ khí, độ ngấu, …)
- Định giá là mối quan tâm chính (có field `business.price_vnd` nhưng logic giá không phải ontology)

---

## 2. Các loại entity cấp cao nhất

Có **8 loại entity cấp cao**. Mọi thứ trong knowledge base đều là một trong số này, hoặc là quan hệ giữa chúng.

```
[Torch]  ←──LẮP_VỪA──  [Part]  ──SẢN_XUẤT_BỞI──  [Manufacturer]
   │                     │
   │                     └──THUỘC──  [PartCategory]
   │
   ├──GẮN_LÊN──  [Robot]
   │                     │
   │                     └──SẢN_XUẤT_BỞI──  [Manufacturer]
   │
   ├──DÙNG_QUÁ_TRÌNH──  [WeldingProcess]
   │
   └──CẦN──  [Procedure]
                     │
                     └──CÓ_CẢNH_BÁO──  [SafetyWarning]
```

| # | Entity | Vai trò | Số lượng (data hiện tại) |
|---|--------|---------|--------------------------|
| 1 | **Torch** | Súng hàn vật lý — SKU mà khách hàng mua | 121 |
| 2 | **Part** | Phụ kiện tiêu hao / kết cấu sử dụng cùng torch | 635 |
| 3 | **Robot** | Cánh tay robot mang súng hàn | ~10 series (Motoman MA/AR/MH) |
| 4 | **PartCategory** | Phân loại part (Tip, Nozzle, …) | 38 categories |
| 5 | **WeldingProcess** | Loại quá trình hàn (CO2, MAG, MIG, TIG) | 6 process types |
| 6 | **Procedure** | Quy trình thao tác (lắp ráp hoặc thay thế) | 9 procedures |
| 7 | **SafetyWarning** | Cảnh báo áp dụng cho torch/part/procedure | 16 warnings |
| 8 | **CategoryVocabulary** | Cầu nối Việt ↔ Anh ↔ category chuẩn | 35 vocab entries |

Các cấu trúc còn lại (compatibility edges, consumable sets, process edges, negative rules) là **quan hệ**, không phải entity.

---

## 3. Entity: Torch

### 3.1 Định nghĩa
Một **Torch** là một dụng cụ hàn mang nhãn TOKIN, bán dưới dạng một đơn vị hoàn chỉnh. Mỗi torch có `model_code` duy nhất. Các phiên bản khác nhau về độ dài cáp, cấu hình bracket, hoặc có/không wire-clamp của cùng một torch gốc **KHÔNG phải** là torch riêng — đó là cấu hình của cùng một SKU.

### 3.2 Các field chính

| Field | Kiểu | Bắt buộc | Ghi chú |
|-------|------|----------|---------|
| `model_code` | str | ✓ | Khoá chính. Ví dụ: `TK-308RR`, `YMSA-500W`, `TA-303CDW` |
| `family` | TorchFamily (enum) | ✓ | Một trong 22 giá trị enum — xem §3.3 |
| `current_class` | CurrentClass (enum) | ✓ | Bậc dòng điện danh định: `80A` → `700A` (15 mức) |
| `ecosystem` | Ecosystem (enum) | ✓ | `N`, `D`, `WX`, `TIG`, `HYBRID`. Quyết định khả năng dùng chung phụ kiện. |
| `cooling` | CoolingMethod (enum) | ✓ | `air` (gió) hoặc `water` (nước) |
| `torch_type` | TorchType (enum) | ✓ | `semi_auto`, `automatic`, `robotic_air`, `robotic_water`, `tig_manual`, `tig_auto` |
| `rated_co2_a` | int | – | Dòng định mức CO2 (torch MIG/MAG) |
| `rated_mag_a` | int | – | Dòng định mức MAG |
| `rated_dc_a` | int | – | Dòng định mức DC (torch TIG) |
| `duty_cycle_pct` | int | – | Chu kỳ làm việc mặc định 0-100 |
| `wire_size` | str | – | Khoảng kích thước dây, vd `"0.8-1.2mm"`. TIG: **không áp dụng**. |
| `tungsten_mm` | str | – | Chỉ TIG. Khoảng tungsten, vd `"0.5-3.2"`. |
| `connection_types` | list[ConnectionSymbol] | – | `N`, `D`, `DD`, `AD`, `BZ`, `LE`, `MIL` |
| `shock_sensor_type` | ShockSensorType | – | `NONE`, `TR`, `SRC`, `YMHS` |
| `cable_length_m` | list[float] | – | Các độ dài cáp có sẵn |
| `source` | str | ✓ | Trích dẫn trang catalog: `"Cat03_p2"` |
| `note` | str | – | Mô tả tự do |
| `business` | BusinessInfo | – | Thông tin giá (xem §10) |
| `compatible_parts` | list[str] | – | Cache danh sách `Part.tokin_part_no`. **DENORMALIZED** — nguồn gốc là `torch_part_mappings`. |
| `tpm_count` | int | – | Đếm TPM (tự động tính) |

### 3.3 Phân loại family

22 family, gom thành 6 super-family:

```
SUPER-FAMILY        FAMILIES                          PROTOTYPE             SỐ LƯỢNG
─────────────────────────────────────────────────────────────────────────────────────
SEMI_AUTO_MIG       TL, TLA, CSL, CSH, CSHA, CSA      TL-20, CSH-50          30
ROBOTIC_MIG_AIR     ACC, TK, SRCT, TR,                TK-308RR, ACC-308RR    23
                    YMXA, YMSA, YMENS, DSRC
ROBOTIC_MIG_WATER   WX, FAM_YMSA_WX                   WX500S, YMSA-500W      12
AUTOMATIC_MIG       A, D                              A-350S, D-500R          8
TIG_MANUAL          TA, FX, FXS, CS                   TA-26, FXSA-150        39
─────────────────────────────────────────────────────────────────────────────────────
```

**Vì sao `FAM_YMSA_WX` được tách thành family riêng**: YMSA-500W và YMSA-508W về cơ học là torch họ YMSA, nhưng sử dụng phụ kiện ecosystem WX (NEW β/WX nozzle, water-cooled). Chúng tạo thành một family lai, kế thừa mounting MA-bracket từ YMSA nhưng kế thừa khả năng dùng chung phụ kiện từ WX. Không tách thì query theo ecosystem sẽ sai.

**Vì sao FXS tách khỏi FX**: FXSA-150, FXSA-200, FXSW-225 có **đầu tháo rời được** (Coil Element + Rubber Boot + Torch Body tách rời), trong khi FX-9, FX-17, FX-25, FX-26 là kết cấu liền khối. Khác biệt kiến trúc dẫn đến phụ kiện thay thế khác nhau.

### 3.4 Phân loại ecosystem

`Ecosystem` là trục phân loại **quan trọng nhất**. Nó quyết định **torch dùng được phụ kiện nào**.

| Ecosystem | Mô tả | Ren tip | Cỡ nozzle | Số lượng |
|-----------|-------|---------|-----------|----------|
| **N** | Tokin MIG/MAG chuẩn. Tip = M6×1, 45mm. Phổ biến nhất. | M6×1, 45mm | 16/19mm | 61 torch |
| **D** | Tương thích Daihen MIG/MAG. Tip = M6×1, 40.5mm (ngắn hơn). | M6×1, 40.5mm | 13/16mm | 5 torch |
| **WX** | Phụ kiện water-cooled NEW β/WX. Nozzle dài 82.5L riêng biệt. | Adapter NEW β/WX | 16/19 (NEW β) | 12 torch |
| **TIG** | Tungsten electrode + cốc sứ/lava. Không dùng tip. | n/a | n/a | 39 torch |
| **HYBRID** | YMSA-500W/508W: thân YMSA + nozzle WX ecosystem. | Adapter NEW β/WX | WX nozzles | 4 torch |

**Bất biến**: Trong ecosystem `N`, mọi Tip đều khớp được với mọi Nozzle. **Khác ecosystem thì phụ kiện KHÔNG dùng chung** trừ khi có edge rõ ràng cho phép. Quy tắc này được ép buộc bởi 17 `negative_rules` (xem §6.3).

---

## 4. Entity: Part

### 4.1 Định nghĩa
Một **Part** là bất kỳ SKU nào được TOKIN liệt kê ở cấp dưới torch. Bao gồm phụ kiện tiêu hao (tip, nozzle), thành phần kết cấu (torch body, inner tube), phụ tùng (bracket, mặt bích, đồ gá), và vật tư mau hỏng (liner, O-ring).

### 4.2 Các field chính

| Field | Kiểu | Bắt buộc | Ghi chú |
|-------|------|----------|---------|
| `tokin_part_no` | str | ✓ | Khoá chính. Mã catalog Tokin: `001002`, `034115`, `YJ1305273` |
| `category` | PartCategory (enum) | ✓ | Một trong 38 giá trị enum — xem §4.3 |
| `ecosystem` | Ecosystem | ✓ | Phải khớp với torch dùng part này |
| `current_class` | CurrentClass | ✓ | `350A` / `500A` / `ALL` (dùng chung) |
| `display_name_en` | str | ✓ | Tên tiếng Anh theo catalog |
| `display_name_vi` | str | ✓ | Tên tiếng Việt (theo CategoryVocab) |
| `p_part_nos` | list[str] | – | Mã tương đương Panasonic (cho replacement chéo brand) |
| `d_part_nos` | list[str] | – | Mã tương đương Daihen |
| `wire_size_mm` | float / str | – | Cỡ dây áp dụng (chỉ Tip, Liner, Inner Tube) |
| `total_length_mm` | float | – | Chiều dài thực |
| `bore_mm` | float | – | Đường kính lỗ (Nozzle) |
| `od_mm` | float | – | Đường kính ngoài (Nozzle) |
| `wire_material` | WireMaterial | – | `steel`, `aluminum`, `flux_core`, `n/a` |
| `supported_processes` | list[WeldingProcessType] | – | `CO2`, `MAG`, `MIG`, `TIG`, `FLUX_CORED` |
| `applicable_torches` | list[str] | – | Cache danh sách model_code — xem cảnh báo dưới |
| `source` | str | ✓ | Trích dẫn catalog |
| `confidence` | float | – | Điểm tin cậy 0.0-1.0 cho dữ liệu trích xuất |
| `note` | str | – | Mô tả tự do |
| `business` | BusinessInfo | – | Thông tin giá |

⚠ **Cảnh báo denormalization**: Field `applicable_torches` trên Part và `compatible_parts` trên Torch chỉ là **cache tiện lợi**. Nguồn gốc thực sự về tương thích nằm ở `torch_part_mappings` và `compatibility_edges`. Khi build lại cache, suy diễn TỪ hai bảng đó, không phải ngược lại.

### 4.3 Phân loại PartCategory — 38 categories

Gom nhóm theo chức năng:

```
NHÓM                            CATEGORIES                                            ECOSYSTEM
─────────────────────────────────────────────────────────────────────────────────────────────
Phụ kiện tiêu hao MIG/MAG       Tip, Nozzle, Orifice, Insulator, WaveWasher           N + D
                                LinerORing
Kết cấu MIG/MAG                 TipBody, TipAdapter, TorchBody, InnerTube,            N + D
                                InsulationCollar, GuideTube, Liner
Lắp ráp đặc biệt WX             WXCenterCeramic, WXNozzleAdapter, WXNozzleSpacer,     chỉ WX
                                WXNozzleNut, WXCoverRubber, WXNozzleSleeve
Joăng / cao su                  ORing, InsulationSpacer, Gasket                       tất cả
Dụng cụ                         Tool                                                  tất cả
Cáp & ống                       CableAssembly, GasHose, PowerCable                    tất cả
Tiêu hao TIG                    TungstenElectrode, Collet, ColletBody,                chỉ TIG
                                GasLensColletBody, CeramicNozzle, LavaNozzle,
                                BackCap, GasLensInsulator, Handle
Làm mát / conduit               CoolantHose, FlexibleConduit                          tất cả
Gắn lên robot                   RobotBracket, RobotFlange, RobotAdapter,              N (MIG robotic)
                                AlignmentFixture
```

**Đã khai báo nhưng chưa dùng** (có trong schema, chưa có instance): `RobotAdapter`, `CoolantHose`, `FlexibleConduit`. Giữ lại để future-proof.

---

## 5. Entity: Robot

### 5.1 Định nghĩa
Một **Robot** là cánh tay manipulator mang súng hàn robot. Không model nội bộ robot — chỉ đủ để xác định tương thích với torch.

### 5.2 Các field chính (enum RobotSeries)

| RobotSeries | Nhà sản xuất | Torch families tương thích | Kiểu mounting |
|-------------|--------------|----------------------------|---------------|
| `MA1440` | Yaskawa Motoman | YMXA, YMSA, FAM_YMSA_WX | MA (cáp trong) |
| `MA2010` | Yaskawa Motoman | YMXA, YMSA, FAM_YMSA_WX | MA (cáp trong) |
| `MH24` | Yaskawa Motoman | TK, SRCT, ACC | MH (cáp ngoài) |
| `AR1440` | Yaskawa Motoman | TR, ACC, TK | MH hoặc MA |
| `AR2010` | Yaskawa Motoman | TR, ACC, TK | MH hoặc MA |
| `AR1730` | Yaskawa Motoman | YMXA, YMSA | MA |
| `AR700` | Yaskawa Motoman (EA) | YMENS | MA-EA |
| `AR900` | Yaskawa Motoman (EA) | YMENS | MA-EA |
| `AR1440E` | Yaskawa Motoman (EA) | YMENS | MA-EA |

### 5.3 Các kiểu mounting (enum MountingType)
- `MA` = cáp gắn bên trong (cáp luồn trong cánh tay robot)
- `MH` = cáp gắn bên ngoài (cáp chạy dọc ngoài cánh tay)
- `MA-EA` = mounting nội bộ riêng cho series EA

---

## 6. Quan hệ

### 6.1 LẮP_VỪA / `compatibility_edges` (1000 edges)
**Cardinality**: Part ↔ Part (trong chuỗi lắp ráp)

**Loại edge**: Part `from_part` tương thích cơ học để lắp kế / lắp vào `to_part`.

Ví dụ:
```json
{
  "from_part": "002001",
  "to_part":   "003002",
  "edge_type": "Tip→Orifice",
  "confidence": 1.0,
  "source": "Cat02_p1"
}
```

**Chiều quan trọng**: Tip→Orifice khác với Orifice→Tip. Phía "from" theo quy ước là phần trong / phần đực / phần được lắp vào; "to" là phần nhận. Điều này quan trọng cho thứ tự lắp ráp.

### 6.2 LẮP_VÀO / `torch_part_mappings` (1015 mappings)
**Cardinality**: Torch ↔ Part (kèm vai trò và cờ bắt buộc)

Bảng nguồn gốc xác định tương thích torch→part.

```json
{
  "torch_model": "TK-308RR",
  "ref_no": "1",
  "part_nos": ["002001","002002","002003"],
  "part_role": "Tip",
  "is_mandatory": true,
  "source": "Cat03_p2",
  "confidence": 1.0
}
```

**Vì sao `part_nos` là list**: Ở slot "Tip" của TK-308RR, user chọn MỘT trong `002001` (0.9mm), `002002` (1.0mm), hoặc `002003` (1.2mm) tuỳ cỡ dây. Đây là quan hệ HOẶC, không phải VÀ.

### 6.3 KHÔNG_TƯƠNG_THÍCH / `negative_rules` (17 rules)
**Cardinality**: PartCategory ↔ PartCategory (cấm chéo ecosystem)

Encode "cái gì KHÔNG BAO GIỜ hoạt động", override mọi edge positive có thể bị suy diễn sai từ pattern chung.

Ví dụ cấu trúc rule (`N_TIP_D_ORIFICE`):
- Tip ecosystem N không dùng được Orifice ecosystem D.
- Lý do: sai khớp ren / vị trí ngồi vật lý.
- Danh sách ngoại lệ: `[]` (không có — tuyệt đối).

Các rule này áp dụng ở **cấp category**, không phải cấp part. Thêm 1 D-Orifice mới sẽ tự động bị cấm ghép với mọi N-Tip mà không cần đổi rule.

### 6.4 DÙNG_CHO_QUÁ_TRÌNH / `process_edges` (359 edges)
**Cardinality**: Part ↔ WeldingProcess (kèm ràng buộc vật liệu dây)

Phát biểu: "Part X hỗ trợ quá trình Y khi dùng với dây vật liệu Z."

Ví dụ: Tip `002001` hỗ trợ `CO2 + dây thép` và `MAG + dây thép`, nhưng KHÔNG `MIG + nhôm` (cần tip nhôm chuyên dụng `002023`).

### 6.5 DÙNG_KHÍ / `gas_flow_edges` (24 edges)
**Cardinality**: Torch ↔ ShieldGasType

Ghi lại đường khí chạy qua khoang khí torch. Dùng để chẩn đoán kiểu "tại sao khí rò từ orifice?".

### 6.6 ĐÓNG_GÓI_NHƯ / `consumable_sets` (9 sets)
**Cardinality**: 1 set → N parts (định nghĩa bộ kit)

Bộ phụ kiện tiêu hao được đóng gói bán theo set. Ví dụ: "Bộ tái tạo torch 350A water-cooled" = nozzle + orifice + tip body + 5 tip + 2 O-ring.

### 6.7 KẾ_THỪA_TỪ / `coverage_inheritance` (10 mappings trong assembly_procedures)
**Cardinality**: Torch → Torch (con trỏ kế thừa)

Khi torch X chia sẻ quy trình lắp ráp với torch cha Y. Ví dụ: `YMENS-300R inherits_from YMSA-300R` — cùng inner tube, cùng chiều dài liner thò ra, cùng bracket. Cho phép bot trả lời "thay inner tube cho YMENS-300R" bằng cách điều hướng sang quy trình YMSA-300R.

---

## 7. Tri thức quy trình

### 7.1 Entity: Procedure

Một **Procedure** là chuỗi thao tác vật lý có thứ tự mà kỹ thuật viên thực hiện.

**Hai subtype**:

| Subtype | Khi kích hoạt | Ví dụ |
|---------|---------------|-------|
| `AssemblySequence` | Lắp ráp torch / kit mới | `asm_wx_air_cooled_nozzle`, `asm_torch_connection` |
| `ReplacementProcedure` | Thay phụ kiện đã mòn / hỏng | `rep_tip_body`, `rep_liner`, `rep_ymsa500w_tip_adapter` |

Mỗi procedure có:
- `id` (khoá chính)
- `name`, `trigger` (text tự do)
- `torch_context` (danh sách model_code hoặc wildcard family)
- `steps` (danh sách có thứ tự `{order, action, part_role, part_id?, note?}`)
- `tools` (danh sách dụng cụ cần)
- `cautions` (cảnh báo inline)
- `torque_ref` (FK → `torque_specs.id`)
- `source` (trích dẫn catalog)

### 7.2 Entity: TorqueSpec

Bảng tham chiếu standalone — không phải quy trình mà là hằng số.

```
torque_tip           = 3.0 N·m
torque_tip_adapter   = 8.0 N·m
torque_tip_body      = 8.0 N·m
handy_tip_changer    = 2.5–3.0 N·m (khoảng)
```

Procedure tham chiếu chéo bằng `torque_ref` để tránh trùng lặp.

### 7.3 Bảng tham chiếu (lookup helper)

Không phải entity — là bảng để join vào procedure:

| Bảng | Số dòng | Trả lời câu hỏi |
|------|---------|-----------------|
| `inner_tube_length_table` | 24 | "Inner tube part nào + dài bao nhiêu cho torch X?" |
| `liner_length_table` | 6 | "Liner SKU nào cho torch X + robot Y + cỡ dây Z?" |
| `liner_protrusion_table` | 45 | "Liner thò ra bao nhiêu mm khỏi cáp nguồn cho torch X?" |
| `liner_protrusion_inner_tube_offset` | 2 | "Cộng 35mm (YMXA) hoặc 125mm (YMSA) nếu dùng inner tube tuỳ chọn" |

### 7.4 Entity: SafetyWarning

Mỗi cảnh báo mang:
- `id` (khoá chính)
- `context` (khi nào áp dụng)
- `text` (nội dung cảnh báo — điều gì có thể xảy ra)
- `severity` (`critical`, `high`, `medium`, `low`)
- `applies_to` (danh sách model_code hoặc `"all torches"`)
- `source`

**16 cảnh báo đang dùng**. Ví dụ severity critical:
- `electric_shock_charged_parts` — dây/tip CÓ ĐIỆN khi torch đang ON
- `confined_space_suffocation` — argon đẩy oxy ra
- `sealed_tank_pipe_explosion` — không bao giờ hàn bình kín có áp suất

Cảnh báo được tham chiếu TỪ:
- `replacement_procedures.cautions` (inline)
- `troubleshooting.related_warnings` (khi triệu chứng khớp)
- `assembly_sequences.warning` (1 block / sequence)

### 7.5 Entity: TroubleshootingCase

Bộ ba "triệu chứng → nguyên nhân khả nghi → hành động khuyến cáo". Hiện 5 case:

| ID | Triệu chứng | Hành động khuyến cáo |
|----|-------------|----------------------|
| `ts_wire_feeding_unstable` | Cấp dây không trơn | Thay liner → nếu còn, thay inner tube |
| `ts_ground_fault` | Chạm mass sau khi lắp lại | Bôi keo silicone lên insulation spacer |
| `ts_gas_leak` | Rò khí chỗ liner | Thay O-ring của liner (036035) |
| `ts_torch_body_damaged_threads` | Ren torch body bị tước | Thay torch body, vặn lực 8 N·m |
| `ts_center_ceramic_cracked` | Ceramic giữa WX bị nứt | Thay ceramic, siết tip body cẩn thận |

---

## 8. Tầng từ vựng / ngôn ngữ

### 8.1 CategoryVocabulary (35 entries)

Cầu nối từ ngôn ngữ tự nhiên Việt / Anh sang giá trị enum `PartCategory` chuẩn. Đây là cái cho phép "béc hàn", "bec han" (không dấu), "contact tip", và "Tip" đều resolve về cùng một category.

```python
{
  "canonical_category": "Tip",
  "vi_terms": ["béc hàn", "bec han", "đầu tip", "dau tip"],
  "en_terms": ["tip", "contact tip", "welding tip"],
  "common_misspellings": ["bec","becs","tép"],
  "search_boost": 1.2
}
```

Đây là **từ điển**, không phải ontology. Nó nằm trong tài liệu ontology vì độ chính xác retrieval phụ thuộc vào nó.

### 8.2 ConnectionSymbol (7 giá trị)

Ký hiệu 2 ký tự encode tương thích đầu cấp dây (feeder):

| Symbol | Ý nghĩa | Được dùng bởi |
|--------|---------|---------------|
| `N` | Yaskawa MOTOPAC / Panasonic feeder | 9 trong 10 torch họ TK |
| `D` | Daihen direct | DSRC, một số TK variants |
| `DD` | Daihen CMRE-741/742 type | Dòng Daihen mới |
| `AD` | Tokin adapter type | Adapter chuyển đổi |
| `BZ` | BINZEL adapter | Tích hợp EU |
| `LE` | Lincoln direct | Thị trường Bắc Mỹ |
| `MIL` | Miller direct | Thị trường Bắc Mỹ |

Field `connection_types` của torch là list vì nhiều SKU torch ship với đầu cáp chưa định — khách chọn loại feeder khi đặt hàng.

---

## 9. Vòng đời và xuất xứ

### 9.1 Enum LifecycleStatus
| Status | Ý nghĩa |
|--------|---------|
| `active` | Đang bán; mặc định cho 121 torch và 635 part |
| `superseded` | Có model mới thay thế |
| `discontinued` | Không còn sản xuất |
| `replacement_only` | Vẫn bán nhưng chỉ làm spare part, không phải sản phẩm chính |

### 9.2 Enum CatalogSource (xuất xứ dữ liệu)
Mọi fact trong knowledge base mang field `source` trích dẫn trang catalog gốc:
- `Cat01_p2` (Product Catalogue 2024, trang 2)
- `Cat02_p7` (Replacement Parts 2017, trang 7)
- `Cat03_p3` (Air-Cooled Robotic Torches 2015, trang 3)
- `Cat04_p10` (TIG Welding Torches, trang 10)
- `Cat05_p6` (Instruction Manual 12/2024, trang 6)
- `Inferred` — suy ra từ rule ecosystem chung, không có nguồn trực tiếp

Cho phép tái tạo phần KB khi có ấn bản catalog mới.

---

## 10. Model giá (tách riêng)

Mỗi Torch và Part có block `business` tuỳ chọn:

```python
{
  "price_vnd": 18500000,
  "price_unit": "cái",
  "price_note": "Liên hệ để báo giá...",
  "is_contact_price": True,
  "is_priority_sell": False,
  "price_updated": "2026-05",
  "price_tier": "mock_v1"
}
```

**Vì sao giá tách khỏi ontology**: Giá thay đổi hàng tuần. Ontology thay đổi hàng năm. Trộn chung sẽ buộc cả ontology phải bump version mỗi lần refresh giá.

---

## 11. Bất biến (Invariants) — quy tắc PHẢI giữ

Đây là các assertion có thể test. Nếu bất kỳ cái nào fail, knowledge base hỏng.

| # | Bất biến | Nơi enforce |
|---|----------|-------------|
| 1 | Mọi Torch có `family` ∈ enum TorchFamily | Pydantic validation |
| 2 | Mọi Part có `category` ∈ enum PartCategory | Pydantic validation |
| 3 | Mọi `torch_part_mappings.torch_model` resolve được về Torch trong data | Check dangling-ref |
| 4 | Mọi `torch_part_mappings.part_nos[i]` resolve được về Part trong data | Check dangling-ref |
| 5 | Mọi `compatibility_edges.from_part` và `.to_part` resolve về Part | Check dangling-ref |
| 6 | Nếu Torch.ecosystem = N thì mọi part không phổ quát đều có ecosystem ∈ {N, ALL} | CHƯA enforce — TODO |
| 7 | Không có negative_rule mâu thuẫn với compatibility_edge | CHƯA enforce — TODO |
| 8 | Family set của Matrix == Data == Schema | Verify bằng sync test |
| 9 | `Procedure.torque_ref` resolve về `TorqueSpec.id` | Check cross-ref |
| 10 | `TroubleshootingCase.related_warnings` resolve về `Warning.id` đang có | Check cross-ref |

Bất biến 1-5 và 8-10 hiện đang **được enforce** (pass với v11g/v1.2). Bất biến 6-7 là **mục tiêu** — sẽ thêm vào retrieval_eval suite.

---

## 12. Chính sách versioning

### 12.1 Cái gì kích hoạt bump version

| Loại thay đổi | Bump | Ví dụ |
|---------------|------|-------|
| Thêm/bỏ loại entity ontology | MAJOR (v3 → v4) | Thêm `Workpiece` thành entity mới |
| Thêm giá trị enum mới (TorchFamily, PartCategory) | MINOR | Thêm family `FXS` |
| Thêm field mới vào entity hiện có | MINOR | Thêm `tig_family` vào Torch |
| Thêm instance mới (torch SKU, part SKU) | PATCH | Thêm TA-350 |
| Sửa lỗi typo / value | PATCH | Sửa wire size |
| Cập nhật giá | KHÔNG (giá ngoài ontology) | – |

### 12.2 Sự đồng bộ phiên bản giữa các file

4 file có số phiên bản độc lập nhưng phải test cùng nhau:

| File | Phiên bản hiện tại | Quản lý |
|------|--------------------|---------|
| `tokinarc_schema_v11_r5.py` | r5 | Enum, Pydantic class, validation rule |
| `tokinarc_data_v11g.json` | v11g | Instance Torch + Part |
| `compatibility_matrix_v11g.py` | v11g | Compatibility edge, TPM |
| `assembly_procedures_v1_2.json` | v1.2 | Procedure, safety, bảng lookup |

Một "release" là bộ 4 file `{schema, data, matrix, assembly}` đã verify end-to-end. Release hiện tại: **schema r5 + data v11g + matrix v11g + assembly v1.2**.

---

## 13. Câu hỏi mở / lỗ hổng đã biết

Đây là các thiếu sót đã biết của ontology hiện tại. Mỗi cái là ứng viên cho v3.x hoặc v4.

| # | Lỗ hổng | Tác động | Ưu tiên |
|---|---------|----------|---------|
| 1 | Không có entity `Workpiece` / `BaseMetal` riêng | Không trả lời được "súng nào cho tấm inox 5mm?" | Trung bình |
| 2 | Không có entity `WireFeeder`, chỉ là string trong assembly | Không reason được bộ ba feeder ↔ torch ↔ cable | Thấp |
| 3 | `PowerCable` có category nhưng không có entity riêng cho biến thể cáp | 10 biến thể power cable nằm ở assembly_procedures, không ở data['parts'] | Trung bình |
| 4 | `LifecycleStatus` đã khai báo nhưng mọi instance đều `active` — chưa track vòng đời thực | Không gợi ý được thay thế cho part đã ngừng SX | Trung bình |
| 5 | Không có entity `Supplier` / `DistributorRegion` | Pricing/stock riêng cho Aggeny VN chưa model được | Thấp |
| 6 | Ontology kết quả hàn (rỗ, văng, độ ngấu) vắng mặt | Không chẩn đoán được câu hỏi về chất lượng mối hàn kém | Cao nhưng ngoài catalog |
| 7 | Robot model lưu dạng string trong field `robot_compatibility`, không phải entity Robot thật | Không Robot nào có row riêng — chỉ ngầm định | Trung bình |
| 8 | Không có entity `Manufacturer` first-class (TOKIN/Panasonic/Daihen/OTC) | `p_part_nos` và `d_part_nos` là string list denormalized | Thấp |

---

## 14. Cách dùng tài liệu này

**Cho developer mở rộng KB**:
1. Đọc §2 để xác định entity nào bị ảnh hưởng bởi thay đổi.
2. Check §11 bất biến — thay đổi không được phá vỡ chúng.
3. Bump version theo chính sách §12.
4. Cập nhật tài liệu này TRƯỚC, rồi mới cập nhật code/data.

**Cho retrieval engineer**:
- §8 từ vựng cho biết ngôn ngữ người dùng map về category chuẩn thế nào.
- §6 quan hệ cho biết các edge nào tồn tại để traverse graph.
- §11 bất biến định nghĩa câu hỏi nào trả lời được với độ tin cậy cao (đã verify) vs heuristic (chưa verify).

**Cho kỹ sư QA / eval**:
- §11 là test charter — mỗi bất biến nên có ít nhất 1 test.
- §13 là danh sách known-failure — không generate test case phụ thuộc vào các lỗ hổng này.

**Cho team kinh doanh / sales (Aggeny VN)**:
- §10 cô lập pricing — team non-technical chỉ động vào field `business.*`.
- §13.5 + §13.8 giải thích vì sao pricing/distributor data riêng cho VN chưa ontology-driven.

---

*Hết Ontology v3.0*
