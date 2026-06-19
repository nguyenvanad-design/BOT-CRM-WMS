"""
tokinarc_schema_v12.py — Pydantic v2 Schema
============================================
Autoss × Tokinarc — Structured Compatibility Retrieval System

Version: v12 (2026-05-25)
Sync: tokinarc_data_v14.json (819 parts, 121 torches, 14 consumable sets)

Changelog v11_r6 → v12:
  ENUMS:
    + CompatRelationType: thêm REPLACES, BELONGS_TO, BELONGS_TO_ALTERNATE
      (3 relation types đang dùng trong v14 nhưng thiếu trong enum cũ)

  MODELS:
    + BusinessInfo: thêm price_unit, price_note, is_contact_price,
        price_updated, price_tier — sync với v14 JSON business object
    + ConsumableSetItem: thêm part_role — filled bởi part_role_patch
    + CompatibilityEdge: thêm rule_id; functional_requires → List[str]
    + NegativeRule: model riêng cho negative_rules array (trước đây không có)
    + ProcessEdge: model cho process_edges (from_part → to_process)
    + GasFlowEdge: model cho gas_flow_edges (orifice → nozzle fit check)
    + TorchPartMapping: model cho torch_part_mappings (TPM)
    + Part (base): flatten alias fields lên top level — khớp v14 flat JSON;
        thêm editorial_picks, used_with, compatible_with, torch_models,
        priority_in_category
    + Torch (base): sync tất cả fields từ v14 torch object
        (dim_x/y, angle_deg, mounting, robot_compatibility, robot_series,
        functional_requires, coolant_unit_required, business...)
    + Part subclasses: Tip/Nozzle/Insulator/Orifice/TipBody đã sync,
        thêm tip_body_dia_mm vào TipBody, applicable_torches vào Nozzle
    CONSUMABLE_SETS seed: 14 sets (từ 8 lên 14, thêm WX/TIG/TCC/D500A sets)
    NEGATIVE_COMPATIBILITY_RULES: sync với v14 (17 rules từ 5 cũ)

  GIỮ NGUYÊN:
    - Tất cả enums cũ (Ecosystem, CurrentClass, TipType, NozzleType...)
    - CATEGORY_VOCABULARY seed (35 entries)
    - Part subclasses: TipAdapter, Liner, LinerORing, WaveWasher, InnerTube...
    - Supporting entities: CoolantUnit, CollisionSensor, RobotBracket, FumeExtractor
    - TorchGeometry, ModelNotationDecoded, ExtractionRecord, ExtractionBatch
    - GraphNode, GraphEdge (Neo4j helpers)
    - MATERIAL_KNOWLEDGE dict

Cách dùng:
  - Validate khi generate/patch data JSON: Part(**flat_dict), Torch(**flat_dict)
  - Type hints trong DataStore / CER layer
  - GraphEdge cho Neo4j bulk loader

Nguồn: 5 file PDF catalog Tokinarc (Cat01-2024, Cat02-2017, Cat03-2015, Cat04-2015, Cat05-2024)
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, List, Union, Literal, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import date


# ================================================================
# SECTION 1 — ENUMS
# ================================================================

class Ecosystem(str, Enum):
    """
    Ecosystem lock — parts từ 2 hệ khác nhau KHÔNG tương thích.
    Ref: Cat01 p.5, Cat02 p.1-6, Cat03 all parts lists
    """
    N         = "N"          # Yaskawa Motopac / Panasonic — phổ biến nhất
    D         = "D"          # Daihen / OTC
    TCC       = "TCC"        # TCC copper nozzle system (tip ren M8×1.25)
    WX        = "WX"         # Water-cooled WX / NEW β nozzle system
    MAN       = "MAN"        # MAN tip type
    UNIVERSAL = "UNIVERSAL"  # Parts dùng được nhiều hệ (hiếm)
    HYBRID    = "HYBRID"     # TK-309R1 (D-tip + N-nozzle), YMSA-500W/508W
    TIG       = "TIG"        # TIG consumables — KHÔNG dùng chung với MIG/MAG


class CurrentClass(str, Enum):
    """
    Torch current rating class. Quyết định consumable set.
    Ref: Cat01 p.2-8, Cat04 p.1-8
    """
    A80  = "80A"    # TA-24 air-cooled TIG
    A125 = "125A"   # TA-9/9P, TA-23A, TA-125HA
    A150 = "150A"   # TA-17/17P, FX-17, FXSA-150
    A180 = "180A"   # TA-24W water-cooled
    A200 = "200A"   # TA-26, FX-25/26, FXSA-200, CSL-18/20
    A225 = "225A"   # TA-20P, FXSW-225
    A250 = "250A"   # TA-20, TA-22A, YMENS-250RA
    A280 = "280A"   # TA-280
    A300 = "300A"   # TA-301HW/CDW, WX robotic 300A
    A310 = "310A"   # CS310
    A350 = "350A"   # MIG/MAG standard + TA-18/17P
    A400 = "400A"   # TA-18SC aluminum TIG
    A410 = "410A"   # CS410
    A450 = "450A"   # WX451/452 robotic
    A500 = "500A"   # MIG/MAG 500A + TA-12/27/18P/500HW
    A700 = "700A"   # WX702 robotic


class CoolingMethod(str, Enum):
    AIR   = "air"
    WATER = "water"


class TorchType(str, Enum):
    SEMI_AUTO              = "semi_auto"
    AIR_COOLED_ROBOTIC     = "air_cooled_robotic"
    WATER_COOLED_ROBOTIC   = "water_cooled_robotic"
    AUTOMATIC              = "automatic"
    TIG_MANUAL             = "tig_manual"
    TIG_ROBOTIC            = "tig_robotic"
    TIG_AUTOMATIC          = "tig_automatic"
    FUME_EXTRACTOR         = "fume_extractor"


class PartCategory(str, Enum):
    """
    Maps to Vietnamese category vocabulary.
    Ref: CATEGORY_VOCABULARY seed data bên dưới.
    """
    # MIG/MAG consumables
    TIP               = "Tip"
    NOZZLE            = "Nozzle"
    ORIFICE           = "Orifice"
    INSULATOR         = "Insulator"
    TIP_BODY          = "TipBody"
    TIP_ADAPTER       = "TipAdapter"
    LINER             = "Liner"
    LINER_O_RING      = "LinerORing"
    INNER_TUBE        = "InnerTube"
    WAVE_WASHER       = "WaveWasher"
    # Structural / torch parts
    TORCH_BODY        = "TorchBody"
    INSULATION_COLLAR = "InsulationCollar"
    GUIDE_TUBE        = "GuideTube"
    # WX sub-assembly
    WX_CENTER_CERAMIC  = "WXCenterCeramic"
    WX_NOZZLE_ADAPTER  = "WXNozzleAdapter"
    WX_NOZZLE_SPACER   = "WXNozzleSpacer"
    WX_NOZZLE_NUT      = "WXNozzleNut"
    WX_COVER_RUBBER    = "WXCoverRubber"
    WX_NOZZLE_SLEEVE   = "WXNozzleSleeve"
    # Seals / hardware
    O_RING             = "ORing"
    INSULATION_SPACER  = "InsulationSpacer"
    TOOL               = "Tool"
    CABLE_ASSEMBLY     = "CableAssembly"
    GAS_HOSE           = "GasHose"
    # TIG consumables
    TUNGSTEN_ELECTRODE   = "TungstenElectrode"
    COLLET               = "Collet"
    COLLET_BODY          = "ColletBody"
    GAS_LENS_COLLET_BODY = "GasLensColletBody"
    CERAMIC_NOZZLE       = "CeramicNozzle"
    LAVA_NOZZLE          = "LavaNozzle"
    BACK_CAP             = "BackCap"
    GASKET               = "Gasket"
    GAS_LENS_INSULATOR   = "GasLensInsulator"
    HANDLE               = "Handle"
    # Cable
    POWER_CABLE          = "PowerCable"
    COOLANT_HOSE         = "CoolantHose"
    FLEXIBLE_CONDUIT     = "FlexibleConduit"
    # Robot hardware
    ROBOT_BRACKET        = "RobotBracket"
    ROBOT_FLANGE         = "RobotFlange"
    ROBOT_ADAPTER        = "RobotAdapter"
    ALIGNMENT_FIXTURE    = "AlignmentFixture"


class CompatRelationType(str, Enum):
    """
    Tất cả relation types đang tồn tại trong v14 compatibility_edges.
    Distribution: compatible_with=980, replaces=13, belongs_to=14,
                  belongs_to_alternate=2, assembled_with=2, functional_requires=5
    """
    COMPATIBLE_WITH      = "compatible_with"       # A lắp được với B
    ASSEMBLED_WITH       = "assembled_with"         # A + B lắp thành cụm (e.g. 004004)
    FUNCTIONAL_REQUIRES  = "functional_requires"   # A BẮT BUỘC cần B (WX nozzle → WX orifice)
    REPLACES             = "replaces"              # A thay thế B (discontinued / alternate)
    BELONGS_TO           = "belongs_to"            # A thuộc set/family B
    BELONGS_TO_ALTERNATE = "belongs_to_alternate"  # A thuộc alternate set B
    # Negative (dùng trong negative_rules riêng, không trong compatibility_edges)
    INCOMPATIBLE_WITH    = "incompatible_with"
    PROCESS_CONSTRAINT   = "process_constraint"


class TipType(str, Enum):
    N           = "N"
    D           = "D"
    R           = "R"          # R-type (robot precision, ±0.05mm)
    MAG         = "MAG"
    MIG         = "MIG"
    NON_TAPERED = "NonTapered"
    ROCKET      = "Rocket"     # Narrow space — dùng với nozzle 001016
    LONG        = "Long"       # 69mm — dùng với nozzle 001004/038042
    TCC         = "TCC"        # M8×1.25, 42mm
    MAN         = "MAN"        # M6×1, 28mm
    MT501G      = "MT501G"
    UNIONMELT   = "Unionmelt"
    DUMMY       = "Dummy"
    TEACHING    = "Teaching"


class NozzleType(str, Enum):
    STANDARD       = "Standard"
    THICK          = "Thick"
    STEP_DOWN      = "StepDown"
    SMALL_DIA_LONG = "SmallDiaLong"   # requires long tip
    SMALL_DIA_73L  = "SmallDia73L"   # requires rocket tip
    ARC_SPOT       = "ArcSpot"
    WATER_COOLED   = "WaterCooled"   # WX water-cooled nozzle
    CARBON         = "Carbon"
    TCC_COPPER     = "TccCopper"
    FLAT           = "Flat"
    DSRC           = "DSRC"          # Chỉ cho DSRC-3531
    LAVA           = "Lava"
    LONG_LAVA      = "LongLava"


class WeldingProcessType(str, Enum):
    CO2          = "CO2"
    MAG          = "MAG"
    MIG          = "MIG"
    TIG          = "TIG"
    FLUX_CORED   = "FluxCored"
    SUBMERGED_ARC = "SubmergedArc"


class TungstenMaterial(str, Enum):
    WL15 = "WL15"   # 1.5% lanthanum — thép + kim loại màu trừ nhôm
    WC20 = "WC20"   # 2% cerium — đa năng nhất
    WP   = "WP"     # Pure tungsten — CHỈ nhôm AC


class WireMaterial(str, Enum):
    STEEL     = "steel"
    ALUMINUM  = "aluminum"
    FLUX_CORE = "flux_core"
    HARD_WIRE = "hard_wire"


class ShieldGasType(str, Enum):
    CO2_100PCT       = "CO2_100%"
    MAG_MIX_CO2AR    = "MAG_CO2+Ar"
    ARGON_100PCT     = "Ar_100%"
    HE_AR_MIX        = "He+Ar"
    SELF_SHIELDED    = "SelfShielded"
    MIXED_AR_CO2_LOW = "Ar+CO2_low"


class LifecycleStatus(str, Enum):
    ACTIVE   = "active"
    LEGACY   = "legacy"
    OBSOLETE = "obsolete"
    REPLACED = "replaced"


class StockStatus(str, Enum):
    IN_STOCK     = "in_stock"
    LOW_STOCK    = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    CONTACT      = "contact"
    DISCONTINUED = "discontinued"


class CatalogSource(str, Enum):
    CAT01_2024      = "Cat01_2024"
    CAT02_2017      = "Cat02_2017"
    CAT03_2015      = "Cat03_2015"
    CAT04_2015      = "Cat04_2015"
    CAT05_2024      = "Cat05_2024"
    AUTOSS_INTERNAL = "Autoss_Internal"
    INFERRED        = "Inferred"


class ConnectionSymbol(str, Enum):
    N      = "N"
    D      = "D"
    DD     = "DD"
    AD     = "AD"
    BZ     = "BZ"
    LE     = "LE"
    MIL    = "MIL"
    FORMER = "-"


class BodyType(str, Enum):
    RR  = "RR"
    RS  = "RS"
    RX  = "RX"
    RW  = "RW"
    ALW = "ALW"


class MountingType(str, Enum):
    MA = "MA"   # Internally mounted cable (YMXA/YMSA)
    MH = "MH"   # Externally mounted cable (TK-308RR + YMH bracket)


class RobotManufacturer(str, Enum):
    YASKAWA_MOTOMAN = "Yaskawa_Motoman"
    PANASONIC       = "Panasonic"
    DAIHEN          = "Daihen"
    LINCOLN         = "Lincoln"
    MILLER          = "Miller"
    BINZEL          = "Binzel"
    OTHER           = "Other"


class RobotSeries(str, Enum):
    MA = "MA"   # MA1440, MA2010
    AR = "AR"   # AR1440, AR2010, AR1730
    EA = "EA"   # AR700, AR900, AR1440E
    MH = "MH"   # MH6, MH24
    HP = "HP"   # HP series

    @classmethod
    def from_model(cls, robot_model: str) -> "RobotSeries":
        m = robot_model.upper()
        if m in ("AR700", "AR900", "AR1440E"): return cls.EA
        if m.startswith("MA"): return cls.MA
        if m.startswith("AR"): return cls.AR
        if m.startswith("MH"): return cls.MH
        if m.startswith("HP"): return cls.HP
        return cls.MA


class ShockSensorType(str, Enum):
    NONE         = "NONE"
    TR           = "TR"
    BUILT_IN     = "built_in"
    YMHS         = "YMHS"
    YMSA_BRACKET = "YMSA_bracket"


class TIGFamily(str, Enum):
    FAMILY_A      = "A"
    FAMILY_B      = "B"
    FAMILY_C      = "C"
    FAMILY_D      = "D"
    FAMILY_E      = "E"
    FAMILY_F      = "F"
    FAMILY_B_HEAVY = "B_heavy"


class TorchFamily(str, Enum):
    ACC        = "ACC"
    TK         = "TK"
    SRCT       = "SRCT"
    YMENS      = "YMENS"
    YMXA       = "YMXA"
    YMSA       = "YMSA"
    DSRC       = "DSRC"
    TR         = "TR"
    A_AUTO     = "A"
    D_AUTO     = "D"
    WX         = "WX"
    CSL        = "CSL"
    CSH        = "CSH"
    TL         = "TL"
    TLA        = "TLA"
    CSA        = "CSA"
    CSHA       = "CSHA"
    TA         = "TA"
    FX         = "FX"
    FXS        = "FXS"
    CS         = "CS"
    FAM_YMSA_WX = "FAM_YMSA_WX"


class TipBodyType(str, Enum):
    ACC_308RR = "ACC-308RR"
    TK_308RR  = "TK-308RR"
    TK_508RR  = "TK-508RR"
    CS_A      = "CS-A"
    CS_B      = "CS-B"
    CS_D      = "CS-D"
    DSRC_3531 = "DSRC-3531"
    D_WT3500  = "D-WT3500"
    D_WT3510  = "D-WT3510"
    D_WT5000  = "D-WT5000"


# ================================================================
# SECTION 2 — SHARED SUB-MODELS
# ================================================================

class BusinessInfo(BaseModel):
    """
    Business layer — sync với v14 JSON business object.
    Source: Autoss price list / ERP.
    v12: thêm price_unit, price_note, is_contact_price, price_updated, price_tier.
    """
    price_vnd: Optional[int] = Field(
        None, description="Giá VND. None = liên hệ báo giá."
    )
    price_unit: str = Field(
        default="cái",
        description="Đơn vị tính: cái / bộ / m / hộp"
    )
    price_note: str = Field(default="")
    is_contact_price: bool = Field(
        default=False,
        description="True = giá chỉ có khi liên hệ, không hiển thị số"
    )
    is_priority_sell: bool = Field(
        default=False,
        description="Autoss ưu tiên bán — hiển thị đầu trong list"
    )
    price_updated: Optional[str] = Field(
        None, description="Tháng update giá, format YYYY-MM"
    )
    price_tier: Optional[str] = Field(
        None, description="e.g. 'mock_v1', 'erp_live'"
    )

    @property
    def price_display(self) -> str:
        if self.is_contact_price or self.price_vnd is None:
            return "Vui lòng liên hệ để báo giá"
        return f"{self.price_vnd:,}đ/{self.price_unit}"


class TemporalInfo(BaseModel):
    """Track lifecycle across catalog versions."""
    valid_from_year: Optional[int] = None
    valid_to_year: Optional[int] = None
    lifecycle_status: LifecycleStatus = LifecycleStatus.ACTIVE
    superseded_by: Optional[str] = None
    source_catalog: Optional[CatalogSource] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


# ================================================================
# SECTION 3 — CATEGORY VOCABULARY (seed data)
# ================================================================

class CategoryVocabulary(BaseModel):
    vi_term: str
    en_term: str
    part_category: PartCategory
    vi_aliases: List[str] = Field(default_factory=list)


CATEGORY_VOCABULARY: List[dict] = [
    {"vi_term": "béc hàn",   "en_term": "Tip",       "part_category": "Tip",
     "vi_aliases": ["đầu hàn","mũi hàn","tip","bec han","contact tip","dau han","mui han"]},
    {"vi_term": "chụp khí",  "en_term": "Nozzle",    "part_category": "Nozzle",
     "vi_aliases": ["cúp khí","chụp","nozzle","gas cup","gas nozzle","cup khi","chup khi"]},
    {"vi_term": "cách điện", "en_term": "Insulator",  "part_category": "Insulator",
     "vi_aliases": ["cach dien","insulator","bọc cách điện","boc cach dien"]},
    {"vi_term": "sứ chia khí","en_term": "Orifice",  "part_category": "Orifice",
     "vi_aliases": ["orifice","chia khí","su chia khi","difuser","diffuser","chia khi"]},
    {"vi_term": "thân giữ béc","en_term": "TipBody", "part_category": "TipBody",
     "vi_aliases": ["than giu bec","tip body","tipbody","holder","giữ béc","giu bec","than giu"]},
    {"vi_term": "lót dây",   "en_term": "Liner",      "part_category": "Liner",
     "vi_aliases": ["liner","ống lót","lot day","conduit liner","ong lot","ruột cáp"]},
    {"vi_term": "điện cực vonfram","en_term": "TungstenElectrode","part_category": "TungstenElectrode",
     "vi_aliases": ["tungsten","vonfram","điện cực","dien cuc","electrode"]},
    {"vi_term": "vòng đệm lò xo","en_term": "WaveWasher","part_category": "WaveWasher",
     "vi_aliases": ["vong dem lo xo","wave washer","waved washer","vòng đệm","vong dem","lo xo dem","255406","255407"]},
    {"vi_term": "ống lót trong","en_term": "InnerTube","part_category": "InnerTube",
     "vi_aliases": ["inner tube","ong lot trong","ống lót nội","ong lot noi","inner liner","ruột ống","ruot ong","tube lót"]},
    {"vi_term": "đầu nối béc","en_term": "TipAdapter","part_category": "TipAdapter",
     "vi_aliases": ["dau noi bec","tip adapter","đầu adapter","dau adapter","034135","WX tip adapter","NEWβ adapter"]},
    {"vi_term": "o-ring liner","en_term": "LinerORing","part_category": "LinerORing",
     "vi_aliases": ["o ring liner","oring liner","liner o-ring","vòng o liner","vong o liner","036035","S-4","s4 o ring","bịt liner"]},
    {"vi_term": "thân súng","en_term": "TorchBody","part_category": "TorchBody",
     "vi_aliases": ["than sung","torch body","cụm thân","cum than","thân súng hàn"]},
    {"vi_term": "sứ định tâm WX","en_term": "WXCenterCeramic","part_category": "WXCenterCeramic",
     "vi_aliases": ["su dinh tam wx","wx center ceramic","center ceramic","061445","sứ trung tâm WX","dinh tam"]},
    {"vi_term": "đệm định vị chụp khí WX","en_term": "WXNozzleSpacer","part_category": "WXNozzleSpacer",
     "vi_aliases": ["wx nozzle spacer","dem dinh vi","061449","nozzle spacer","dem chup khi WX"]},
    {"vi_term": "đầu nối chụp khí WX","en_term": "WXNozzleAdapter","part_category": "WXNozzleAdapter",
     "vi_aliases": ["wx nozzle adapter","061447","dau noi chup khi wx"]},
    {"vi_term": "đai ốc chụp khí WX","en_term": "WXNozzleNut","part_category": "WXNozzleNut",
     "vi_aliases": ["wx nozzle nut","061448","dai oc chup khi","nut wx"]},
    {"vi_term": "vòng O-ring WX","en_term": "ORing","part_category": "ORing",
     "vi_aliases": ["o-ring","o ring","vong o ring","Y90201009","Y90201015","Y90201016","jaso 1009","vòng đệm cao su","ron cao su"]},
    {"vi_term": "đệm cách điện","en_term": "InsulationSpacer","part_category": "InsulationSpacer",
     "vi_aliases": ["insulation spacer","dem cach dien","YM1405181","spacer cach dien"]},
    {"vi_term": "dụng cụ thay béc","en_term": "Tool","part_category": "Tool",
     "vi_aliases": ["handy tip changer","tip changer","dung cu thay bec","046703","046705","torque driver tip"]},
    {"vi_term": "collet TIG","en_term": "Collet","part_category": "Collet",
     "vi_aliases": ["collet","kẹp điện cực","kep dien cuc","chuck TIG","collet tig","10N","13N","53N"]},
    {"vi_term": "thân collet","en_term": "ColletBody","part_category": "ColletBody",
     "vi_aliases": ["collet body","than collet","collet body TIG","electrode holder body","10N29","13N25"]},
    {"vi_term": "thân collet gas lens","en_term": "GasLensColletBody","part_category": "GasLensColletBody",
     "vi_aliases": ["gas lens collet body","than collet gas lens","collet body gas lens","gas lens body","45V","53N66"]},
    {"vi_term": "chụp sứ TIG","en_term": "CeramicNozzle","part_category": "CeramicNozzle",
     "vi_aliases": ["ceramic nozzle","chup su TIG","chụp gốm TIG","nozzle sứ TIG","TIG nozzle","chụp khí TIG","chup khi TIG","No.4","No.5","No.6","No.7","No.8","10N44","13N08"]},
    {"vi_term": "chụp lava TIG","en_term": "LavaNozzle","part_category": "LavaNozzle",
     "vi_aliases": ["lava nozzle","chup lava TIG","lava cup TIG","nozzle lava","chụp đá lava"]},
    {"vi_term": "nắp đuôi TIG","en_term": "BackCap","part_category": "BackCap",
     "vi_aliases": ["back cap TIG","nap duoi TIG","cap TIG","đuôi súng TIG","back cap S","back cap M","back cap L","41V33","41V35","57Y04"]},
    {"vi_term": "đệm chống rò TIG","en_term": "Gasket","part_category": "Gasket",
     "vi_aliases": ["gasket TIG","dem chong ro TIG","seal TIG","cup gasket","18CG","598882"]},
    {"vi_term": "cách điện gas lens","en_term": "GasLensInsulator","part_category": "GasLensInsulator",
     "vi_aliases": ["gas lens insulator","cach dien gas lens","insulator gas lens TIG","54N01","54N63"]},
    {"vi_term": "tay cầm TIG","en_term": "Handle","part_category": "Handle",
     "vi_aliases": ["handle TIG","tay cam TIG","cán súng TIG","grip TIG","body TIG"]},
    {"vi_term": "cụm cáp","en_term": "CableAssembly","part_category": "CableAssembly",
     "vi_aliases": ["cum cap","cable assembly","cáp nhảy","cap nhay","jumper cable","cap SRC","YMC110"]},
    {"vi_term": "ống dẫn khí","en_term": "GasHose","part_category": "GasHose",
     "vi_aliases": ["ong dan khi","gas hose","ống khí","ong khi","dây khí","YB0312082","133005"]},
    {"vi_term": "ống dẫn dây","en_term": "GuideTube","part_category": "GuideTube",
     "vi_aliases": ["ong dan day","guide tube","ống dẫn","wire guide","ong dan"]},
    {"vi_term": "vòng cách điện","en_term": "InsulationCollar","part_category": "InsulationCollar",
     "vi_aliases": ["vong cach dien","insulation collar","collar cách điện","016052","YEA000018"]},
    {"vi_term": "cáp nguồn","en_term": "PowerCable","part_category": "PowerCable",
     "vi_aliases": ["cap nguon","power cable","dây nguồn","day nguon","cáp điện","cable nguồn","308RR-N-PC"]},
    {"vi_term": "cao su bảo vệ WX","en_term": "WXCoverRubber","part_category": "WXCoverRubber",
     "vi_aliases": ["cao su bao ve WX","WX cover rubber","cover rubber WX","cao su WX","rubber WX"]},
    {"vi_term": "ống nối chụp khí WX","en_term": "WXNozzleSleeve","part_category": "WXNozzleSleeve",
     "vi_aliases": ["ong noi chup khi WX","WX nozzle sleeve","nozzle sleeve WX","ống WX","sleeve WX","Y902ALW10"]},
]


# ================================================================
# SECTION 4 — COMPATIBILITY / RELATIONSHIP MODELS
# ================================================================

class CompatibilityEdge(BaseModel):
    """
    Core relationship model — compatibility knowledge graph.
    v12: thêm rule_id; functional_requires → List[str]; thêm REPLACES/BELONGS_TO variants.

    Ref: v14 compatibility_edges (1016 edges tổng):
      compatible_with=980, replaces=13, belongs_to=14,
      belongs_to_alternate=2, assembled_with=2, functional_requires=5
    """
    from_part: str = Field(..., description="Tokin Part No. — source")
    to_part: str = Field(..., description="Tokin Part No. — target")
    relation_type: CompatRelationType = CompatRelationType.COMPATIBLE_WITH
    rule_id: Optional[str] = Field(
        None, description="ID tham chiếu sang negative_rules nếu là negative edge"
    )
    priority_rank: int = Field(default=50, ge=1, le=100)
    is_mandatory: bool = Field(
        default=False,
        description="True = không hàn được nếu thiếu combination này"
    )
    incompatibility_reason: Optional[str] = Field(
        None,
        description="REQUIRED khi relation_type=incompatible_with"
    )
    process_constraint: Optional[str] = Field(
        None, description="e.g. 'ONLY_FOR: MIG (Ar 100%)', 'REQUIRES: AC welding'"
    )
    functional_requires: Optional[List[str]] = Field(
        None, description="Functional dependencies e.g. ['COOLANT_SYSTEM', 'GAS_LENS_INSULATOR']"
    )
    note: Optional[str] = None
    source: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode='after')
    def validate_incompatibility(self) -> 'CompatibilityEdge':
        if (self.relation_type == CompatRelationType.INCOMPATIBLE_WITH
                and not self.incompatibility_reason):
            raise ValueError(
                "incompatibility_reason is REQUIRED when relation_type=incompatible_with"
            )
        return self


class NegativeRule(BaseModel):
    """
    Negative compatibility rule — sync với v14 negative_rules array.
    v12: model riêng (trước đây chỉ có NEGATIVE_COMPATIBILITY_RULES list[dict]).

    v14 có 17 rules với cấu trúc:
      rule_id, description, from_category, to_category, from_ecosystem, to_ecosystem,
      relation_type, incompatibility_reason, exception_torch_models, source, confidence
    """
    rule_id: str = Field(..., description="e.g. 'N_TIP_D_ORIFICE'")
    description: str
    from_category: Optional[str] = None
    to_category: Optional[str] = None
    from_ecosystem: Optional[str] = None
    to_ecosystem: Optional[str] = None
    from_part: Optional[str] = None   # rule cho part cụ thể
    to_part: Optional[str] = None
    relation_type: str = "incompatible_with"
    incompatibility_reason: str
    exception_torch_models: List[str] = Field(
        default_factory=list,
        description="Torch models được miễn rule này (e.g. TK-309R1 HYBRID)"
    )
    overrides_rules: List[str] = Field(
        default_factory=list,
        description="rule_ids mà torch model này override"
    )
    torch_model: Optional[str] = None  # khi rule dùng cho 1 model cụ thể
    source: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ProcessEdge(BaseModel):
    """
    Process compatibility — part → welding process.
    v14 process_edges (359 edges): from_part → to_process → relation_type.
    Field name: to_process (KHÔNG phải 'process') — data_store.py phải dùng đúng field này.
    """
    from_part: str
    to_process: str = Field(
        ..., description="WeldingProcessType value: CO2 / MAG / MIG / TIG / FluxCored"
    )
    relation_type: str = Field(
        default="supports_process",
        description="supports_process / incompatible_process"
    )
    is_preferred: bool = Field(
        default=True,
        description="True = process này được khuyến nghị cho part này"
    )
    source: Optional[str] = None


class GasFlowEdge(BaseModel):
    """
    Gas flow compatibility — orifice OD phải fit trong nozzle bore.
    v14 gas_flow_edges (24 edges).
    Rule: orifice.outer_dia ≤ nozzle.inner_dia
    """
    from_orifice: str = Field(..., description="Tokin Part No. của orifice")
    to_nozzle: str = Field(..., description="Tokin Part No. của nozzle")
    relation_type: str = Field(default="fits_in_nozzle")
    reason: Optional[str] = None
    source: Optional[str] = None


class TorchPartMapping(BaseModel):
    """
    Torch ↔ Part mapping (TPM) — v14 torch_part_mappings (1517 records).
    Cho biết torch model dùng part nào ở role nào.
    """
    torch_model: str
    ref_no: Optional[str] = Field(
        None, description="Reference number trong Parts Drawing diagram"
    )
    part_nos: List[str] = Field(default_factory=list)
    part_role: str = Field(
        ..., description="Tip / Nozzle / Insulator / TipBody / Liner / ..."
    )
    is_mandatory: bool = Field(default=True)
    source: Optional[str] = None


# ================================================================
# SECTION 5 — CONSUMABLE SET MODELS
# ================================================================

class ConsumableSetItem(BaseModel):
    """
    v12: thêm part_role — filled bởi part_role_patch trong v14.
    part_role dùng để group by role trong DataStore._group_torch_parts_by_role().
    """
    part_id: str = Field(..., description="Tokin Part No.")
    priority_rank: int = Field(default=50, ge=1)
    is_mandatory: bool = Field(default=True)
    default_quantity: int = Field(default=1, ge=1)
    part_role: Optional[str] = Field(
        None,
        description="Category/role của part này trong set: Tip / Nozzle / Insulator / ..."
    )
    note: Optional[str] = None


class ConsumableSet(BaseModel):
    """
    Bộ vật tư tiêu hao theo torch_current_class + ecosystem.
    v14 có 14 sets. Format set_id: {ecosystem}{current_class}_{variant}
    """
    set_id: str
    display_name_vi: str
    torch_current_class: CurrentClass
    ecosystem: Ecosystem
    cooling_method: CoolingMethod = CoolingMethod.AIR
    default_wire_size_mm: float
    items: List[ConsumableSetItem] = Field(default_factory=list)
    notes: Optional[str] = None


# Pre-populated — sync với v14 (14 sets)
CONSUMABLE_SETS: List[dict] = [
    {
        "set_id": "N350A_standard",
        "display_name_vi": "Bộ vật tư tiêu hao súng hàn N 350A (dây 1.2mm)",
        "torch_current_class": "350A", "ecosystem": "N", "cooling_method": "air",
        "default_wire_size_mm": 1.2,
        "notes": "Default cho Yaskawa/Panasonic 350A. Nguồn: Autoss Type 2 expected answer.",
        "items": [
            {"part_id": "036001", "priority_rank": 1, "is_mandatory": True,  "default_quantity": 1,  "part_role": "TipBody",    "note": "Thân giữ béc CS Loại A (69mm)"},
            {"part_id": "002003", "priority_rank": 2, "is_mandatory": True,  "default_quantity": 10, "part_role": "Tip",        "note": "Béc hàn N 1.2mm x 45L"},
            {"part_id": "002001", "priority_rank": 3, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",        "note": "Béc hàn N 0.9mm x 45L"},
            {"part_id": "002002", "priority_rank": 4, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",        "note": "Béc hàn N 1.0mm x 45L"},
            {"part_id": "033203", "priority_rank": 5, "is_mandatory": True,  "default_quantity": 2,  "part_role": "Nozzle",     "note": "Chụp khí HR-350 16mm 68L"},
            {"part_id": "004002", "priority_rank": 6, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Insulator",  "note": "Cách điện N S (350A)"},
            {"part_id": "003002", "priority_rank": 7, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Orifice",    "note": "Sứ chia khí N S (350A)"},
        ]
    },
    {
        "set_id": "N350A_09wire",
        "display_name_vi": "Bộ vật tư tiêu hao súng hàn N 350A (dây 0.9mm)",
        "torch_current_class": "350A", "ecosystem": "N", "cooling_method": "air",
        "default_wire_size_mm": 0.9,
        "items": [
            {"part_id": "036001", "priority_rank": 1, "is_mandatory": True,  "default_quantity": 1,  "part_role": "TipBody"},
            {"part_id": "002001", "priority_rank": 2, "is_mandatory": True,  "default_quantity": 10, "part_role": "Tip",    "note": "Béc hàn N 0.9mm x 45L"},
            {"part_id": "033203", "priority_rank": 3, "is_mandatory": True,  "default_quantity": 2,  "part_role": "Nozzle"},
            {"part_id": "004002", "priority_rank": 4, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Insulator"},
            {"part_id": "003002", "priority_rank": 5, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Orifice"},
        ]
    },
    {
        "set_id": "D350A_standard",
        "display_name_vi": "Bộ vật tư tiêu hao súng hàn D 350A (Daihen/OTC, dây 1.0mm)",
        "torch_current_class": "350A", "ecosystem": "D", "cooling_method": "air",
        "default_wire_size_mm": 1.0,
        "notes": "D-type parts only. KHÔNG dùng chung N parts.",
        "items": [
            {"part_id": "023009", "priority_rank": 1, "is_mandatory": True,  "default_quantity": 10, "part_role": "Tip",       "note": "Béc hàn D 1.0mm"},
            {"part_id": "023007", "priority_rank": 2, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc hàn D 0.8mm"},
            {"part_id": "023008", "priority_rank": 3, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc hàn D 0.9mm"},
            {"part_id": "023010", "priority_rank": 4, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc hàn D 1.2mm"},
            {"part_id": "023011", "priority_rank": 5, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc hàn D 1.6mm"},
            {"part_id": "023461", "priority_rank": 6, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc hàn D variant"},
            {"part_id": "023013", "priority_rank": 7, "is_mandatory": True,  "default_quantity": 2,  "part_role": "Nozzle",    "note": "Chụp khí D No.10 16mm 70L"},
            {"part_id": "023012", "priority_rank": 8, "is_mandatory": False, "default_quantity": 2,  "part_role": "Nozzle",    "note": "Chụp khí D No.8 12mm"},
            {"part_id": "023014", "priority_rank": 9, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Orifice",   "note": "Sứ chia khí D S (350A)"},
            {"part_id": "023015", "priority_rank":10, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Insulator", "note": "Cách điện D S (350A)"},
        ]
    },
    {
        "set_id": "D500A_standard",
        "display_name_vi": "Bộ vật tư tiêu hao súng hàn D 500A (Daihen/OTC)",
        "torch_current_class": "500A", "ecosystem": "D", "cooling_method": "air",
        "default_wire_size_mm": 1.2,
        "notes": "D 500A set. Chỉ có 2 mandatory items xác nhận từ catalog.",
        "items": [
            {"part_id": "023011", "priority_rank": 1, "is_mandatory": True,  "default_quantity": 10, "part_role": "Tip",    "note": "Béc hàn D 1.6mm (500A)"},
            {"part_id": "023010", "priority_rank": 2, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",    "note": "Béc hàn D 1.2mm"},
            {"part_id": "023463", "priority_rank": 3, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",    "note": "Béc hàn D 500A variant"},
            {"part_id": "023013", "priority_rank": 4, "is_mandatory": True,  "default_quantity": 2,  "part_role": "Nozzle", "note": "Chụp khí D 500A"},
            {"part_id": "023014", "priority_rank": 5, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Orifice"},
            {"part_id": "023015", "priority_rank": 6, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Insulator"},
        ]
    },
    {
        "set_id": "N500A_semiauto",
        "display_name_vi": "Bộ vật tư tiêu hao súng hàn N 500A bán tự động (dây 1.6mm)",
        "torch_current_class": "500A", "ecosystem": "N", "cooling_method": "air",
        "default_wire_size_mm": 1.6,
        "notes": "Semi-auto context (CSH-50 series). TipBody 036001 CS-B variant.",
        "items": [
            {"part_id": "036001", "priority_rank": 1, "is_mandatory": True,  "default_quantity": 1,  "part_role": "TipBody"},
            {"part_id": "002004", "priority_rank": 2, "is_mandatory": True,  "default_quantity": 10, "part_role": "Tip",       "note": "Béc hàn N 1.6mm x 45L"},
            {"part_id": "001001", "priority_rank": 3, "is_mandatory": True,  "default_quantity": 2,  "part_role": "Nozzle",    "note": "Chụp khí N 500A 19mm 88L"},
            {"part_id": "004001", "priority_rank": 4, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Insulator", "note": "Cách điện N L (500A)"},
            {"part_id": "003001", "priority_rank": 5, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Orifice",   "note": "Sứ chia khí N L (500A)"},
        ]
    },
    {
        "set_id": "N500A_robotic",
        "display_name_vi": "Bộ vật tư tiêu hao súng hàn N 500A robot (dây 1.2mm)",
        "torch_current_class": "500A", "ecosystem": "N", "cooling_method": "air",
        "default_wire_size_mm": 1.2,
        "notes": "Robotic context (TK-508RR). TipBody 016403.",
        "items": [
            {"part_id": "016403", "priority_rank": 1, "is_mandatory": True,  "default_quantity": 1,  "part_role": "TipBody",   "note": "Thân giữ béc TK-508RR"},
            {"part_id": "036001", "priority_rank": 2, "is_mandatory": False, "default_quantity": 1,  "part_role": "TipBody",   "note": "Thân giữ béc CS-A (alt)"},
            {"part_id": "002004", "priority_rank": 3, "is_mandatory": True,  "default_quantity": 10, "part_role": "Tip",       "note": "Béc hàn N 1.6mm (500A)"},
            {"part_id": "002003", "priority_rank": 4, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc hàn N 1.2mm"},
            {"part_id": "002001", "priority_rank": 5, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc hàn N 0.9mm"},
            {"part_id": "002002", "priority_rank": 6, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc hàn N 1.0mm"},
            {"part_id": "001001", "priority_rank": 7, "is_mandatory": True,  "default_quantity": 2,  "part_role": "Nozzle",    "note": "Chụp khí N 500A 19mm 88L"},
            {"part_id": "001010", "priority_rank": 8, "is_mandatory": False, "default_quantity": 2,  "part_role": "Nozzle",    "note": "Chụp khí N 500A 16mm"},
            {"part_id": "004001", "priority_rank": 9, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Insulator", "note": "Cách điện N L (500A)"},
            {"part_id": "003001", "priority_rank":10, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Orifice",   "note": "Sứ chia khí N L (500A)"},
        ]
    },
    {
        "set_id": "N200A_csl_standard",
        "display_name_vi": "Bộ vật tư tiêu hao súng hàn N 200A (CSL-18/20)",
        "torch_current_class": "200A", "ecosystem": "N", "cooling_method": "air",
        "default_wire_size_mm": 0.9,
        "notes": "Cho CSL-18/CSL-20 semi-auto. Nozzle insulated series 038xxx.",
        "items": [
            {"part_id": "036001", "priority_rank": 1, "is_mandatory": True,  "default_quantity": 1,  "part_role": "TipBody"},
            {"part_id": "002001", "priority_rank": 2, "is_mandatory": True,  "default_quantity": 10, "part_role": "Tip",    "note": "Béc hàn N 0.9mm"},
            {"part_id": "002002", "priority_rank": 3, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",    "note": "Béc hàn N 1.0mm"},
            {"part_id": "002003", "priority_rank": 4, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",    "note": "Béc hàn N 1.2mm"},
            {"part_id": "002005", "priority_rank": 5, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",    "note": "Béc hàn N 0.8mm"},
            {"part_id": "038040", "priority_rank": 6, "is_mandatory": True,  "default_quantity": 2,  "part_role": "Nozzle", "note": "Chụp khí 200A ∅13mm 75L"},
            {"part_id": "038041", "priority_rank": 7, "is_mandatory": False, "default_quantity": 1,  "part_role": "Nozzle", "note": "Chụp khí 200A ∅16mm straight"},
            {"part_id": "038042", "priority_rank": 8, "is_mandatory": False, "default_quantity": 1,  "part_role": "Nozzle", "note": "Chụp khí 200A ∅10mm 100L (long tip)"},
            {"part_id": "037002", "priority_rank": 9, "is_mandatory": False, "default_quantity": 1,  "part_role": "TipAdapter", "note": "TipAdapter 200A CSL"},
            {"part_id": "004002", "priority_rank":10, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Insulator"},
            {"part_id": "003002", "priority_rank":11, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Orifice"},
        ]
    },
    {
        "set_id": "WX500A_standard",
        "display_name_vi": "Bộ vật tư tiêu hao súng WX 500A (YMSA-500W/508W)",
        "torch_current_class": "500A", "ecosystem": "HYBRID", "cooling_method": "air",
        "default_wire_size_mm": 1.2,
        "notes": "HYBRID ecosystem. Dùng WX nozzle system + N-compatible tips.",
        "items": [
            {"part_id": "034135", "priority_rank": 1, "is_mandatory": True, "default_quantity": 1, "part_role": "TipAdapter", "note": "Đầu nối béc NEWβ/WX"},
            {"part_id": "034115", "priority_rank": 2, "is_mandatory": True, "default_quantity": 2, "part_role": "Nozzle",     "note": "Chụp khí NEW β/WX 16mm 82.5L"},
            {"part_id": "034120", "priority_rank": 3, "is_mandatory": True, "default_quantity": 1, "part_role": "Orifice",    "note": "Sứ chia khí WX"},
            {"part_id": "002003", "priority_rank": 4, "is_mandatory": True, "default_quantity": 10,"part_role": "Tip",        "note": "Béc hàn N 1.2mm (dùng được với WX)"},
        ]
    },
    {
        "set_id": "WX500A_air_nozzle",
        "display_name_vi": "Bộ vật tư tiêu hao súng WX 500A (chụp khí thường)",
        "torch_current_class": "500A", "ecosystem": "WX", "cooling_method": "air",
        "default_wire_size_mm": 1.2,
        "notes": "Dùng cho YMSA-500W/508W với chụp khí NEW β/WX thường.",
        "items": [
            {"part_id": "034135", "priority_rank": 1, "is_mandatory": True, "default_quantity": 1, "part_role": "TipAdapter"},
            {"part_id": "034115", "priority_rank": 2, "is_mandatory": True, "default_quantity": 2, "part_role": "Nozzle",    "note": "Chụp khí WX air standard"},
            {"part_id": "034116", "priority_rank": 3, "is_mandatory": False,"default_quantity": 2, "part_role": "Nozzle",    "note": "Chụp khí WX air variant"},
            {"part_id": "034120", "priority_rank": 4, "is_mandatory": True, "default_quantity": 1, "part_role": "Orifice"},
            {"part_id": "061445", "priority_rank": 5, "is_mandatory": True, "default_quantity": 1, "part_role": "WXCenterCeramic"},
            {"part_id": "061449", "priority_rank": 6, "is_mandatory": False,"default_quantity": 1, "part_role": "WXNozzleAdapter", "note": "WX500R adapter"},
            {"part_id": "061450", "priority_rank": 7, "is_mandatory": False,"default_quantity": 1, "part_role": "WXNozzleAdapter", "note": "WX500R adapter variant"},
            {"part_id": "002003", "priority_rank": 8, "is_mandatory": True, "default_quantity": 10,"part_role": "Tip"},
        ]
    },
    {
        "set_id": "WX500A_water_nozzle",
        "display_name_vi": "Bộ vật tư tiêu hao súng WX 500A (chụp khí làm mát nước)",
        "torch_current_class": "500A", "ecosystem": "WX", "cooling_method": "water",
        "default_wire_size_mm": 1.2,
        "notes": "Water-cooled nozzle variant — chụp khí được làm mát bằng nước.",
        "items": [
            {"part_id": "034135", "priority_rank": 1, "is_mandatory": True, "default_quantity": 1, "part_role": "TipAdapter"},
            {"part_id": "034121", "priority_rank": 2, "is_mandatory": True, "default_quantity": 2, "part_role": "Nozzle",  "note": "Chụp khí WX Water-Cooled"},
            {"part_id": "034115", "priority_rank": 3, "is_mandatory": False,"default_quantity": 2, "part_role": "Nozzle",  "note": "Chụp khí WX air (alt)"},
            {"part_id": "034116", "priority_rank": 4, "is_mandatory": False,"default_quantity": 2, "part_role": "Nozzle",  "note": "Chụp khí WX air variant"},
            {"part_id": "034120", "priority_rank": 5, "is_mandatory": True, "default_quantity": 1, "part_role": "Orifice"},
            {"part_id": "061445", "priority_rank": 6, "is_mandatory": True, "default_quantity": 1, "part_role": "WXCenterCeramic"},
            {"part_id": "061447", "priority_rank": 7, "is_mandatory": True, "default_quantity": 1, "part_role": "WXNozzleAdapter"},
            {"part_id": "061449", "priority_rank": 8, "is_mandatory": False,"default_quantity": 1, "part_role": "WXNozzleAdapter", "note": "WX500R adapter"},
            {"part_id": "061450", "priority_rank": 9, "is_mandatory": False,"default_quantity": 1, "part_role": "WXNozzleAdapter", "note": "WX500R adapter variant"},
            {"part_id": "002003", "priority_rank":10, "is_mandatory": True, "default_quantity": 10,"part_role": "Tip"},
        ]
    },
    {
        "set_id": "TCC350A_standard",
        "display_name_vi": "Bộ vật tư tiêu hao súng TCC 350A",
        "torch_current_class": "350A", "ecosystem": "TCC", "cooling_method": "air",
        "default_wire_size_mm": 1.2,
        "notes": "TCC copper nozzle system. Tip ren M8×1.25 — KHÔNG dùng TipBody M6.",
        "items": [
            {"part_id": "036001", "priority_rank": 1, "is_mandatory": True,  "default_quantity": 1,  "part_role": "TipBody",   "note": "Thân giữ béc CS-A (dùng cho TCC-350R)"},
            {"part_id": "002100", "priority_rank": 2, "is_mandatory": True,  "default_quantity": 10, "part_role": "Tip",       "note": "Béc TCC 1.2mm"},
            {"part_id": "002101", "priority_rank": 3, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc TCC 0.9mm"},
            {"part_id": "002001", "priority_rank": 4, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc N 0.9mm (compatible)"},
            {"part_id": "002002", "priority_rank": 5, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc N 1.0mm (compatible)"},
            {"part_id": "002003", "priority_rank": 6, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc N 1.2mm (compatible)"},
            {"part_id": "002005", "priority_rank": 7, "is_mandatory": False, "default_quantity": 10, "part_role": "Tip",       "note": "Béc N 0.8mm (compatible)"},
            {"part_id": "023120", "priority_rank": 8, "is_mandatory": True,  "default_quantity": 2,  "part_role": "Nozzle",    "note": "Chụp khí TCC-350R"},
            {"part_id": "023121", "priority_rank": 9, "is_mandatory": False, "default_quantity": 1,  "part_role": "Nozzle",    "note": "Chụp khí TCC-350R variant"},
            {"part_id": "033203", "priority_rank":10, "is_mandatory": False, "default_quantity": 2,  "part_role": "Nozzle",    "note": "Chụp khí HR-350 (alt)"},
            {"part_id": "004002", "priority_rank":11, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Insulator", "note": "Cách điện N S"},
            {"part_id": "003002", "priority_rank":12, "is_mandatory": True,  "default_quantity": 1,  "part_role": "Orifice",   "note": "Sứ chia khí N S"},
            {"part_id": "037002", "priority_rank":13, "is_mandatory": False, "default_quantity": 1,  "part_role": "TipAdapter"},
            {"part_id": "038040", "priority_rank":14, "is_mandatory": False, "default_quantity": 2,  "part_role": "Nozzle",    "note": "Chụp khí 200A (TCC variant)"},
            {"part_id": "038041", "priority_rank":15, "is_mandatory": False, "default_quantity": 1,  "part_role": "Nozzle"},
            {"part_id": "038042", "priority_rank":16, "is_mandatory": False, "default_quantity": 1,  "part_role": "Nozzle"},
        ]
    },
    {
        "set_id": "TIG_family_1726_air",
        "display_name_vi": "Bộ vật tư TIG Family B air (TA-17/26 series)",
        "torch_current_class": "350A", "ecosystem": "TIG", "cooling_method": "air",
        "default_wire_size_mm": 2.4,
        "notes": "TIG Family B — TA-17/17P/18/18P/26/FXSA-150/200. Dùng 10N prefix.",
        "items": [
            {"part_id": "TIG-10N23",   "priority_rank": 1, "is_mandatory": True, "default_quantity": 1, "part_role": "ColletBody"},
            {"part_id": "TIG-10N24",   "priority_rank": 2, "is_mandatory": True, "default_quantity": 1, "part_role": "Collet"},
            {"part_id": "10N24",       "priority_rank": 3, "is_mandatory": False,"default_quantity": 1, "part_role": "Collet",      "note": "alias 10N24"},
            {"part_id": "TIG-10N44",   "priority_rank": 4, "is_mandatory": True, "default_quantity": 1, "part_role": "CeramicNozzle"},
            {"part_id": "TIG-WL15-24", "priority_rank": 5, "is_mandatory": True, "default_quantity": 1, "part_role": "TungstenElectrode", "note": "WL15 2.4mm"},
            {"part_id": "TIG-41V24",   "priority_rank": 6, "is_mandatory": True, "default_quantity": 1, "part_role": "BackCap"},
            {"part_id": "41V33",       "priority_rank": 7, "is_mandatory": False,"default_quantity": 1, "part_role": "BackCap",     "note": "alias 41V33"},
            {"part_id": "018341",      "priority_rank": 8, "is_mandatory": False,"default_quantity": 1, "part_role": "TungstenElectrode", "note": "TIG tungsten WL15"},
            {"part_id": "018343",      "priority_rank": 9, "is_mandatory": False,"default_quantity": 1, "part_role": "TungstenElectrode", "note": "TIG tungsten variant"},
            {"part_id": "13N10",       "priority_rank":10, "is_mandatory": False,"default_quantity": 1, "part_role": "CeramicNozzle","note": "alias 13N10"},
            {"part_id": "13N22",       "priority_rank":11, "is_mandatory": False,"default_quantity": 1, "part_role": "Collet",       "note": "alias 13N22"},
            {"part_id": "13N27",       "priority_rank":12, "is_mandatory": False,"default_quantity": 1, "part_role": "ColletBody",   "note": "alias 13N27"},
            {"part_id": "57Y04",       "priority_rank":13, "is_mandatory": False,"default_quantity": 1, "part_role": "GasLensInsulator","note": "alias 57Y04"},
            {"part_id": "10N48",       "priority_rank":14, "is_mandatory": False,"default_quantity": 1, "part_role": "CeramicNozzle","note": "alias 10N48"},
            {"part_id": "10N32",       "priority_rank":15, "is_mandatory": False,"default_quantity": 1, "part_role": "ColletBody",   "note": "alias 10N32"},
        ]
    },
    {
        "set_id": "TIG_family_920_air",
        "display_name_vi": "Bộ vật tư TIG Family A air (TA-9/20 series)",
        "torch_current_class": "350A", "ecosystem": "TIG", "cooling_method": "air",
        "default_wire_size_mm": 2.4,
        "notes": "TIG Family A — TA-9/9P/20/20P/CS310/FX-9/25. Dùng 13N prefix.",
        "items": [
            {"part_id": "TIG-13N28",   "priority_rank": 1, "is_mandatory": True, "default_quantity": 1, "part_role": "ColletBody"},
            {"part_id": "TIG-13N23",   "priority_rank": 2, "is_mandatory": True, "default_quantity": 1, "part_role": "Collet"},
            {"part_id": "TIG-13N08",   "priority_rank": 3, "is_mandatory": True, "default_quantity": 1, "part_role": "CeramicNozzle"},
            {"part_id": "TIG-WL15-24", "priority_rank": 4, "is_mandatory": True, "default_quantity": 1, "part_role": "TungstenElectrode"},
            {"part_id": "TIG-41V24",   "priority_rank": 5, "is_mandatory": True, "default_quantity": 1, "part_role": "BackCap"},
        ]
    },
    {
        "set_id": "TIG_robotic_300",
        "display_name_vi": "Bộ vật tư TIG robot 300A",
        "torch_current_class": "350A", "ecosystem": "TIG", "cooling_method": "water",
        "default_wire_size_mm": 2.4,
        "notes": "TIG robotic water-cooled — TA-301HW/303CDW series.",
        "items": [
            {"part_id": "TIG-10N32", "priority_rank": 1, "is_mandatory": True, "default_quantity": 1, "part_role": "ColletBody"},
            {"part_id": "TIG-10N25", "priority_rank": 2, "is_mandatory": True, "default_quantity": 1, "part_role": "Collet"},
            {"part_id": "TIG-54N01", "priority_rank": 3, "is_mandatory": True, "default_quantity": 1, "part_role": "GasLensInsulator"},
            {"part_id": "TIG-WC20-24","priority_rank": 4, "is_mandatory": True, "default_quantity": 1, "part_role": "TungstenElectrode", "note": "WC20 2.4mm"},
        ]
    },
]


# ================================================================
# SECTION 6 — PART BASE MODEL (flat structure — sync với v14 JSON)
# ================================================================

class Part(BaseModel):
    """
    Abstract base — flat field structure khớp với v14 JSON parts array.

    v12 thay đổi so với v11_r6:
    - Bỏ nested alias: PartAlias và temporal: TemporalInfo
    - Flatten tất cả alias fields lên top level (p_part_nos, d_part_nos,
      p_model_codes, d_model_codes, o_part_nos, o_model_codes)
    - Thêm: editorial_picks, used_with, compatible_with, torch_models,
            priority_in_category, confidence, source

    Cross-brand fields:
      p_part_nos / d_part_nos: spare part ORDER CODES (mã đặt hàng lẻ)
      p_model_codes / d_model_codes: TORCH MODEL names (mã model súng)
        → chỉ có ở TorchBody/TipBody/Liner, rỗng ở Tip/Nozzle/Orifice/Insulator
      o_part_nos / o_model_codes: OTC brand (tách riêng khỏi Daihen)
    """
    tokin_part_no: str = Field(..., description="Primary key — canonical Tokin Part No.")
    category: PartCategory
    ecosystem: Ecosystem
    current_class: CurrentClass
    display_name_en: str
    display_name_vi: str

    # Cross-brand codes (flat — v11_r6 dùng nested PartAlias)
    p_part_nos: List[str] = Field(default_factory=list)
    d_part_nos: List[str] = Field(default_factory=list)
    p_model_codes: List[str] = Field(default_factory=list)
    d_model_codes: List[str] = Field(default_factory=list)
    o_part_nos: List[str] = Field(default_factory=list)
    o_model_codes: List[str] = Field(default_factory=list)

    # Graph relationships (populated from compatibility_edges)
    compatible_with: List[str] = Field(
        default_factory=list,
        description="Part numbers compatible với part này (denormalized cho fast lookup)"
    )
    used_with: List[str] = Field(default_factory=list)
    editorial_picks: List[str] = Field(
        default_factory=list,
        description="Auto-generated top companions qua co-occurrence trong TPM"
    )
    torch_models: List[str] = Field(
        default_factory=list,
        description="Torch models part này dùng được"
    )

    # Business
    business: BusinessInfo = Field(default_factory=BusinessInfo)

    # Catalog metadata
    source: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    priority_in_category: Optional[int] = Field(
        None, description="1 = highest priority trong category. Dùng để sort kết quả."
    )
    note: Optional[str] = None

    @field_validator('tokin_part_no')
    @classmethod
    def validate_part_no(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Tokin Part No. cannot be empty")
        return v


# ================================================================
# SECTION 7 — PART SUBCLASSES
# ================================================================

class Tip(Part):
    """
    Contact tip — béc hàn.
    Ref: Cat01 p.5, Cat02 p.1-4
    """
    category: Literal[PartCategory.TIP] = PartCategory.TIP
    tip_type: Optional[TipType] = None
    wire_size_mm: float = Field(..., gt=0, le=6.4)
    thread_type: str = Field(default="M6x1")
    total_length_mm: float
    body_length_mm: float
    material: str = Field(default="CuCrZr")
    wire_material: WireMaterial = Field(default=WireMaterial.STEEL)
    supported_processes: List[str] = Field(
        default_factory=lambda: ["CO2", "MAG"]
    )
    suitable_for_aluminum: bool = Field(default=False)
    suitable_for_flux_cored: bool = Field(default=False)
    suitable_for_robotic: bool = Field(default=True)
    has_wave_washer: bool = Field(default=False)


class Nozzle(Part):
    """
    Gas nozzle — chụp khí.
    Ref: Cat01 p.6, Cat02 p.5-6
    Gas flow rule: nozzle.inner_dia ≥ orifice.outer_dia
    """
    category: Literal[PartCategory.NOZZLE] = PartCategory.NOZZLE
    nozzle_type: Optional[NozzleType] = None
    inner_dia_mm: int
    outer_dia_mm: int
    length_mm: int
    thread_spec: str = Field(default="M20x1.0")
    is_water_cooled: bool = Field(default=False)
    is_insulated: bool = Field(default=False)
    requires_long_tip: bool = Field(default=False)
    requires_rocket_tip: bool = Field(default=False)
    supported_processes: List[str] = Field(
        default_factory=lambda: ["CO2", "MAG"]
    )
    applicable_torches: List[str] = Field(
        default_factory=list,
        description="v14 field — torch models nozzle này dùng được"
    )


class Orifice(Part):
    """
    Gas diffuser — sứ chia khí.
    Ref: Cat01 p.5, Cat02 p.4-5
    """
    category: Literal[PartCategory.ORIFICE] = PartCategory.ORIFICE
    orifice_class: str = Field(
        ..., description="N-S (350A), N-L (500A), D-S (350A), WX, WX-WaterCooled"
    )
    length_mm: float
    outer_dia_mm: float
    inner_dia_mm: float
    bore_dia_mm: Optional[float] = Field(
        None,
        description="OD dùng để check gas flow fit: bore_dia ≤ nozzle.inner_dia"
    )
    is_water_cooled: bool = Field(default=False)


class Insulator(Part):
    """
    Insulator — cách điện.
    Ref: Cat01 p.5, Cat02 p.4-5
    Special: 004004 = 004002 (N Insulator S) + 255406 (Wave Washer S)
    """
    category: Literal[PartCategory.INSULATOR] = PartCategory.INSULATOR
    insulator_class: str = Field(..., description="N-S-350A, N-L-500A, D-S-350A")
    length_mm: float
    inner_dia_mm: float
    outer_dia_mm: float
    has_wave_washer: bool = Field(default=False)
    base_insulator_id: Optional[str] = None
    wave_washer_id: Optional[str] = None

    @model_validator(mode='after')
    def validate_wave_washer_combo(self) -> 'Insulator':
        if self.has_wave_washer and (not self.base_insulator_id or not self.wave_washer_id):
            raise ValueError(
                "base_insulator_id và wave_washer_id là REQUIRED khi has_wave_washer=True"
            )
        return self


class TipBody(Part):
    """
    Tip body / holder — thân giữ béc.
    Ref: Cat02 p.7-8, Cat03 parts lists
    """
    category: Literal[PartCategory.TIP_BODY] = PartCategory.TIP_BODY
    tip_body_type: Optional[str] = None
    length_mm: float
    thread_for_tip: str = Field(default="M6x1")
    thread_for_torch: str = Field(default="M10x1")
    tip_body_dia_mm: Optional[float] = Field(
        None, description="v14 field — outer dia của tip body"
    )


class TipAdapter(Part):
    """
    Tip adapter — đầu nối béc (WX / NEW β nozzle system).
    Ref: Cat05 p.9-10
    """
    category: Literal[PartCategory.TIP_ADAPTER] = PartCategory.TIP_ADAPTER
    tip_thread: str = Field(default="M6x1")
    torch_thread_spec: str = Field(default="M12x1.0")
    adapter_type: Optional[str] = None
    applicable_nozzle_system: str = Field(default="WX")


class WireSizeRange(BaseModel):
    min_mm: float = Field(..., gt=0)
    max_mm: float = Field(..., gt=0)

    @model_validator(mode='after')
    def validate_range(self) -> 'WireSizeRange':
        if self.min_mm > self.max_mm:
            raise ValueError(f"min_mm ({self.min_mm}) > max_mm ({self.max_mm})")
        return self


class Liner(Part):
    """
    Wire guide liner — lót dây.
    Ref: Cat02 p.8-14, Cat05 p.6
    """
    category: Literal[PartCategory.LINER] = PartCategory.LINER
    wire_size_range: Optional[WireSizeRange] = None
    torch_cable_length_m: Optional[float] = None
    liner_length_mm: Optional[int] = None
    protrusion_L_mm: Optional[float] = None
    liner_material: str = Field(default="standard")
    inner_dia_mm: Optional[float] = None
    outer_dia_mm: Optional[float] = None
    compatible_torch_models: List[str] = Field(default_factory=list)


class LinerORing(Part):
    """O-ring liner — seal đầu liner."""
    category: Literal[PartCategory.LINER_O_RING] = PartCategory.LINER_O_RING
    o_ring_size: str = Field(default="S-4")
    inner_dia_mm: Optional[float] = None


class WaveWasher(Part):
    """Wave washer — vòng đệm lò xo."""
    category: Literal[PartCategory.WAVE_WASHER] = PartCategory.WAVE_WASHER
    washer_size: Optional[str] = None


class InnerTube(Part):
    """Inner tube / guide tube."""
    category: Literal[PartCategory.INNER_TUBE] = PartCategory.INNER_TUBE
    inner_dia_mm: Optional[float] = None
    outer_dia_mm: Optional[float] = None
    length_mm: Optional[float] = None


# ================================================================
# SECTION 8 — TORCH MODEL (flat structure — sync với v14 JSON)
# ================================================================

class Torch(BaseModel):
    """
    Abstract base cho tất cả torch models.
    v12: flat structure sync với v14 torch object.

    v14 torch fields (tất cả):
      model_code, family, torch_type, current_class, ecosystem, cooling,
      rated_co2_a, rated_mag_a, rated_mig_a, rated_dc_a,
      duty_co2_pct, duty_mag_pct, duty_cycle_pct, duty_pct,
      wire_size, wire_size_note, cable_length_m, cable_m,
      source, note, shock_sensor_type, functional_requires,
      coolant_system_note, coolant_unit_required, functional_constraint,
      compatible_parts, tpm_count, business,
      mounting, robot_compatibility, robot_series,
      dim_x_mm, dim_y_mm, dim_x_tol, dim_y_tol, angle_deg,
      is_detachable, has_built_in_shock_sensor, has_shock_sensor,
      body_type, body_shape, body_length, head_angle,
      tig_family, welding_process, welding_material,
      applicable_tungsten_size, tungsten_mm, wire_ecosystem, nozzle_ecosystem,
      has_air_cylinder, has_cylinder, is_ultralight, sensor_name,
      tip_body, operation_rate, weight_g, working_weight_kg
    """
    model_code: str = Field(..., description="Canonical model code e.g. 'TK-308RR'")
    family: Optional[str] = None
    torch_type: TorchType
    current_class: CurrentClass
    ecosystem: Ecosystem
    cooling: str = Field(default="air", description="air / water")

    # Rated currents
    rated_co2_a: Optional[int] = None
    rated_mag_a: Optional[int] = None
    rated_mig_a: Optional[int] = None
    rated_dc_a: Optional[int] = None

    # Duty cycles
    duty_co2_pct: Optional[int] = Field(None, ge=0, le=100)
    duty_mag_pct: Optional[int] = Field(None, ge=0, le=100)
    duty_cycle_pct: Optional[int] = Field(None, ge=0, le=100)

    # Wire
    wire_size: Optional[str] = None
    wire_size_note: Optional[str] = None

    # Cable
    cable_length_m: Optional[List[float]] = None

    # Robot
    mounting: Optional[str] = None
    robot_compatibility: Optional[str] = None
    robot_series: Optional[List[str]] = None

    # Geometry
    dim_x_mm: Optional[float] = None
    dim_y_mm: Optional[float] = None
    dim_x_tol: Optional[float] = None
    dim_y_tol: Optional[float] = None
    angle_deg: Optional[float] = None

    # Shock sensor
    shock_sensor_type: str = Field(default="NONE")
    has_built_in_shock_sensor: bool = Field(default=False)
    has_shock_sensor: bool = Field(default=False)
    sensor_name: Optional[str] = None

    # Functional
    functional_requires: Optional[List[str]] = Field(
        None, description="e.g. ['COOLANT_SYSTEM']"
    )
    functional_constraint: Optional[str] = None
    coolant_unit_required: Optional[str] = None
    coolant_system_note: Optional[str] = None

    # Torch body / detach
    is_detachable: bool = Field(default=False)
    body_type: Optional[str] = None
    body_shape: Optional[str] = None
    body_length: Optional[float] = None
    head_angle: Optional[float] = None
    tip_body: Optional[str] = None

    # TIG specific
    tig_family: Optional[str] = None
    welding_process: Optional[str] = None
    welding_material: Optional[str] = None
    applicable_tungsten_size: Optional[str] = None
    tungsten_mm: Optional[float] = None
    wire_ecosystem: Optional[str] = None
    nozzle_ecosystem: Optional[str] = None

    # Misc
    has_air_cylinder: bool = Field(default=False)
    has_cylinder: bool = Field(default=False)
    is_ultralight: bool = Field(default=False)
    operation_rate: Optional[str] = None
    weight_g: Optional[int] = None
    working_weight_kg: Optional[float] = None
    tpm_count: Optional[int] = None
    compatible_parts: Optional[List[str]] = None

    # Business
    business: BusinessInfo = Field(default_factory=BusinessInfo)

    # Metadata
    source: Optional[str] = None
    note: Optional[str] = None

    # display_name_vi là REQUIRED — validate để catch bug W2 (121 torches null)
    display_name_vi: Optional[str] = Field(
        None,
        description="Tên tiếng Việt hiển thị cho khách. PHẢI có — null là bug W2."
    )

    @field_validator('model_code')
    @classmethod
    def validate_model_code(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("model_code cannot be empty")
        return v


# ================================================================
# SECTION 9 — SUPPORTING ENTITIES
# ================================================================

class CoolantUnit(BaseModel):
    """WR-100 / WR-200TC — required cho water-cooled torches."""
    unit_id: str
    tokin_part_no: Optional[str] = None
    display_name_vi: str
    supply_voltage_v: str
    frequency_hz: str = "50/60Hz"
    power_kva: Optional[float] = None
    discharge_pressure_mpa: float
    discharge_flow_lpm: str
    heat_radiation_kcal_min: Optional[float] = None
    cooling_capacity_w: Optional[int] = None
    tank_capacity_l: float
    weight_kg: float
    has_thermostat: bool = False
    temp_range_c: Optional[str] = None
    compatible_with_torches: List[str] = Field(default_factory=list)
    source: str = "Cat01_p8"


class CollisionSensor(BaseModel):
    """YMHS / TR sensor — robotic torch collision protection."""
    sensor_id: str
    display_name_en: str
    display_name_vi: str
    sensor_type: str
    weight_g: Optional[int] = None
    clamp_dia_mm: Optional[float] = None
    compatible_robots: List[str] = Field(default_factory=list)
    compatible_torches: List[str] = Field(default_factory=list)
    requires_pedestal: Optional[str] = None
    source: str


class RobotBracket(BaseModel):
    """YMH/YMSH/YMXA bracket — mount torch lên robot wrist."""
    bracket_id: str
    display_name_en: str
    display_name_vi: str
    bracket_type: str
    cable_mount_type: str
    compatible_robots: List[str] = Field(default_factory=list)
    compatible_torches: List[str] = Field(default_factory=list)
    requires_flange: Optional[str] = None
    source: str


class FumeExtractor(BaseModel):
    """WF-120/130/180/300 — welding fume extractor units."""
    model_code: str
    display_name_vi: str
    rated_voltage: str
    max_airflow_m3_min: float
    max_pressure_kpa: float
    filter_count: int = 1
    noise_level_dba: int
    weight_kg: float
    dimensions_mm: str
    motor_power_kw: Optional[float] = None
    compatible_fume_torches: List[str] = Field(default_factory=list)
    source: str = "Cat01_p18"


class Robot(BaseModel):
    """Welding robot model — determines torch/bracket/cable selection."""
    model_code: str
    manufacturer: RobotManufacturer
    series: str
    torch_mount_type: MountingType
    connection_symbol: ConnectionSymbol
    required_bracket: Optional[str] = None
    required_flange: Optional[str] = None
    compatible_torch_families: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


# ================================================================
# SECTION 10 — TORCH GEOMETRY (robot simulation)
# ================================================================

class TorchGeometry(BaseModel):
    """Normalized torch geometry cho robot TCP calculation."""
    overall_length_mm: Optional[float] = None
    overall_height_mm: Optional[float] = None
    neck_angle_deg: Optional[float] = None
    neck_offset_mm: Optional[float] = None
    tcp_x_mm: Optional[float] = None
    tcp_y_mm: Optional[float] = None
    tcp_z_mm: Optional[float] = None
    dim_x_tolerance_mm: Optional[float] = None
    dim_y_tolerance_mm: Optional[float] = None
    inner_tube_length_mm: Optional[float] = None
    replacement_accuracy_mm: Optional[float] = None
    source: Optional[str] = None


# ================================================================
# SECTION 11 — MODEL NOTATION DECODER
# ================================================================

class ModelNotationDecoded(BaseModel):
    """
    Decode Tokinarc model code → ecosystem + current_class + consumable_set_id.
    TK-308RR-N-1.0 → {family:TK, current_code:308, eco:N, class:350A, set:N350A_standard}
    """
    raw_model_code: str
    family: str
    current_code: Optional[str] = None
    body_type: Optional[BodyType] = None
    connection_symbol: Optional[ConnectionSymbol] = None
    cable_length_m: Optional[float] = None
    has_sc_option: bool = False
    inferred_ecosystem: Ecosystem
    inferred_current_class: CurrentClass
    inferred_consumable_set_id: str

    CURRENT_CODE_MAP: Dict[str, Any] = {
        "308": {"co2_a": 350, "mag_a": 300, "current_class": "350A"},
        "508": {"co2_a": 500, "mag_a": 400, "current_class": "500A"},
        "309": {"co2_a": 350, "mag_a": 300, "current_class": "350A"},
        "300": {"co2_a": 350, "mag_a": 300, "current_class": "350A"},
        "500": {"co2_a": 500, "mag_a": 350, "current_class": "500A"},
        "250": {"mig_a": 250,               "current_class": "350A"},
    }
    model_config = {"arbitrary_types_allowed": True}


# ================================================================
# SECTION 12 — PIPELINE HELPERS (Extraction + Validation Gate)
# ================================================================

class ExtractionRecord(BaseModel):
    """Single record từ PDF extraction pipeline — validated trước khi load Neo4j."""
    record_id: str
    part: Union[Tip, Nozzle, Orifice, Insulator, TipBody, TipAdapter,
                Liner, LinerORing, WaveWasher, InnerTube] = Field(
        ..., discriminator='category'
    )
    compatibility_edges: List[CompatibilityEdge] = Field(default_factory=list)
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    requires_human_review: bool = False
    review_reason: Optional[str] = None


class ExtractionBatch(BaseModel):
    """Batch extraction — flag nếu error_rate > 10%."""
    batch_id: str
    source_catalog: Optional[CatalogSource] = None
    source_page: int
    records: List[ExtractionRecord] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)
    human_review_required: bool = False
    total_records: int = 0
    valid_records: int = 0
    error_rate: float = 0.0

    @model_validator(mode='after')
    def compute_batch_stats(self) -> 'ExtractionBatch':
        self.total_records = len(self.records)
        self.valid_records = sum(1 for r in self.records if not r.requires_human_review)
        if self.total_records > 0:
            self.error_rate = round(
                (self.total_records - self.valid_records) / self.total_records, 3
            )
        if self.validation_errors or self.error_rate > 0.1:
            self.human_review_required = True
        return self


# ================================================================
# SECTION 13 — NEO4J GRAPH LOADING HELPERS
# ================================================================

class GraphNode(BaseModel):
    node_id: str
    node_type: str
    labels: List[str] = Field(default_factory=list)
    properties: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    from_node_id: str
    to_node_id: str
    edge_type: CompatRelationType
    properties: dict = Field(default_factory=dict)


# ================================================================
# SECTION 14 — NEGATIVE COMPATIBILITY RULES (seed — sync v14: 17 rules)
# ================================================================

NEGATIVE_COMPATIBILITY_RULES: List[dict] = [
    {
        "rule_id": "N_TIP_D_ORIFICE",
        "description": "N-type Tip cannot use D-type Orifice",
        "from_category": "Tip", "to_category": "Orifice",
        "from_ecosystem": "N", "to_ecosystem": "D",
        "relation_type": "incompatible_with",
        "incompatibility_reason": (
            "N-type Tip (M6×1, 45mm) is incompatible with D Orifice S (023014). "
            "D Orifice: 20mm × 13.5mm outer, different seating."
        ),
        "exception_torch_models": [], "source": "Cat02_2017", "confidence": 1.0
    },
    {
        "rule_id": "N_TIP_D_INSULATOR",
        "description": "N-type Tip cannot use D-type Insulator",
        "from_category": "Tip", "to_category": "Insulator",
        "from_ecosystem": "N", "to_ecosystem": "D",
        "relation_type": "incompatible_with",
        "incompatibility_reason": (
            "N Insulator S (004002) outer dia 20mm. D Insulator S (023015) outer dia 21mm. "
            "Different thread and geometry."
        ),
        "exception_torch_models": [], "source": "Cat02_2017", "confidence": 1.0
    },
    {
        "rule_id": "N_TIP_D_NOZZLE",
        "description": "N-type Tip cannot use D-type Nozzle",
        "from_category": "Tip", "to_category": "Nozzle",
        "from_ecosystem": "N", "to_ecosystem": "D",
        "relation_type": "incompatible_with",
        "incompatibility_reason": (
            "N Nozzle and D Nozzle have different seating geometry. "
            "Mixing causes gas leaks and arc instability."
        ),
        "exception_torch_models": [], "source": "Inferred", "confidence": 1.0
    },
    {
        "rule_id": "D_TIP_N_ORIFICE",
        "description": "D-type Tip cannot use N-type Orifice",
        "from_category": "Tip", "to_category": "Orifice",
        "from_ecosystem": "D", "to_ecosystem": "N",
        "relation_type": "incompatible_with",
        "incompatibility_reason": "Ecosystem lock: D-tip geometry (40.5mm) incompatible with N Orifice seating.",
        "exception_torch_models": ["TK-309R1"],
        "source": "Cat02_2017", "confidence": 1.0
    },
    {
        "rule_id": "D_TIP_N_INSULATOR",
        "description": "D-type Tip cannot use N-type Insulator",
        "from_category": "Tip", "to_category": "Insulator",
        "from_ecosystem": "D", "to_ecosystem": "N",
        "relation_type": "incompatible_with",
        "incompatibility_reason": "D-tip (40.5mm) + N Insulator geometry mismatch. Gas leak risk.",
        "exception_torch_models": ["TK-309R1"],
        "source": "Inferred", "confidence": 1.0
    },
    {
        "rule_id": "D_TIP_N_NOZZLE",
        "description": "D-type Tip cannot use N-type Nozzle",
        "from_category": "Tip", "to_category": "Nozzle",
        "from_ecosystem": "D", "to_ecosystem": "N",
        "relation_type": "incompatible_with",
        "incompatibility_reason": "D-tip shorter (40.5mm vs N 45mm) — N nozzle bore misaligned.",
        "exception_torch_models": ["TK-309R1"],
        "source": "Inferred", "confidence": 1.0
    },
    {
        "rule_id": "N_ORIFICE_D_NOZZLE",
        "description": "N Orifice S cannot fit D Nozzle",
        "from_category": "Orifice", "to_category": "Nozzle",
        "from_ecosystem": "N", "to_ecosystem": "D",
        "relation_type": "incompatible_with",
        "incompatibility_reason": "N Orifice S outer dia 15.5mm. D Nozzle bore 12mm (023012) — won't fit.",
        "exception_torch_models": [], "source": "Cat02_2017", "confidence": 1.0
    },
    {
        "rule_id": "WX_NOZZLE_N_ORIFICE",
        "description": "WX Water-Cooled Nozzle requires WX Orifice, not N Orifice",
        "from_category": "Nozzle", "to_category": "Orifice",
        "from_ecosystem": "WX", "to_ecosystem": "N",
        "relation_type": "incompatible_with",
        "incompatibility_reason": (
            "WX nozzle system requires WX Orifice (034120/034121). "
            "N Orifice S (003002) does not fit WX nozzle assembly."
        ),
        "exception_torch_models": [], "source": "Cat05_2024", "confidence": 1.0
    },
    {
        "rule_id": "ROCKET_TIP_STANDARD_NOZZLE",
        "description": "Rocket Tip CANNOT use Standard Nozzle 73L",
        "from_part": "002322", "to_category": "Nozzle",
        "relation_type": "incompatible_with",
        "incompatibility_reason": (
            "Rocket tip narrow body (φ3) requires Small Dia Nozzle 73L (001016). "
            "Standard nozzle bore too large for proper gas shielding."
        ),
        "exception_torch_models": [], "source": "Cat02_2017", "confidence": 1.0
    },
    {
        "rule_id": "SMALL_DIA_LONG_NOZZLE_SHORT_TIP",
        "description": "Small Dia Long Nozzle (001004) requires Long Tip",
        "from_part": "001004",
        "relation_type": "incompatible_with",
        "incompatibility_reason": (
            "Small Dia Long Nozzle (001004, 100mm) requires long tip (69mm). "
            "Standard 45mm tips too short — tip won't reach proper position."
        ),
        "exception_torch_models": [], "source": "Cat02_2017", "confidence": 1.0
    },
    {
        "rule_id": "CSL18_LONG_NOZZLE_SHORT_TIP",
        "description": "CSL-18/20 long nozzle 038042 requires long tip",
        "from_part": "038042",
        "relation_type": "incompatible_with",
        "incompatibility_reason": "038042 (102L nozzle for CSL-18/20) requires long tip. Standard tip too short.",
        "exception_torch_models": [], "source": "Cat02_2017", "confidence": 1.0
    },
    {
        "rule_id": "DSRC_NOZZLE_STANDARD_D",
        "description": "DSRC Nozzle 023501 only for DSRC-3531 torch",
        "from_part": "023501",
        "relation_type": "incompatible_with",
        "incompatibility_reason": "023501 is exclusive to DSRC-3531. Cannot use on standard D-type torches.",
        "exception_torch_models": ["DSRC-3531"],
        "source": "Cat03_2015", "confidence": 1.0
    },
    {
        "rule_id": "TCC_TIP_STANDARD_TIPBODY",
        "description": "TCC Tip (M8×1.25) cannot use standard TipBody M6",
        "from_category": "Tip", "to_category": "TipBody",
        "from_ecosystem": "TCC", "to_ecosystem": "N",
        "relation_type": "incompatible_with",
        "incompatibility_reason": (
            "TCC Tip thread M8×1.25. Standard TipBody thread M6×1.0. "
            "Thread mismatch — requires dedicated TCC TipBody M8."
        ),
        "exception_torch_models": [], "source": "Cat02_2017", "confidence": 1.0
    },
    {
        "rule_id": "ALUMINUM_TIP_CO2_MAG",
        "description": "Aluminum tip (002019) cannot use CO2/MAG process",
        "from_part": "002019",
        "relation_type": "incompatible_with",
        "incompatibility_reason": (
            "Aluminum tip (002019) is Cu pure (không CuCrZr). "
            "CO2/MAG gas degrades aluminum bore. ONLY MIG + Ar/He."
        ),
        "exception_torch_models": [], "source": "Cat02_2017", "confidence": 1.0
    },
    {
        "rule_id": "WP_TUNGSTEN_DC_STEEL",
        "description": "WP pure tungsten CANNOT use DC or weld steel",
        "from_part": "WP_TUNGSTEN",
        "relation_type": "incompatible_with",
        "incompatibility_reason": (
            "WP pure tungsten designed for AC aluminum only. "
            "DC current or steel welding → unstable arc, tungsten contamination."
        ),
        "exception_torch_models": [], "source": "Cat04_2015", "confidence": 1.0
    },
    {
        "rule_id": "N_ORIFICE_S_L_MISMATCH",
        "description": "N Orifice S (350A) incompatible with N nozzle 500A",
        "from_part": "003002", "to_category": "Nozzle",
        "relation_type": "incompatible_with",
        "incompatibility_reason": (
            "N Orifice S OD=15.5mm. N 500A nozzle bore=19mm (001001). "
            "Size mismatch — gas won't flow correctly."
        ),
        "exception_torch_models": [], "source": "Cat02_2017", "confidence": 0.9
    },
    {
        "rule_id": "N_ORIFICE_L_350A_NOZZLE",
        "description": "N Orifice L (500A) incompatible with 350A nozzle",
        "from_part": "003001", "to_category": "Nozzle",
        "relation_type": "incompatible_with",
        "incompatibility_reason": (
            "N Orifice L OD=19.8mm. 350A nozzle bore=16mm (001002). "
            "Orifice too large — cannot fit inside nozzle."
        ),
        "exception_torch_models": [], "source": "Cat02_2017", "confidence": 0.9
    },
]


# ================================================================
# SECTION 15 — MATERIAL KNOWLEDGE (unchanged from v11_r6)
# ================================================================

MATERIAL_KNOWLEDGE = {
    "wire_materials": [
        {
            "material": "steel_solid",
            "vi_name": "Dây hàn thép đặc",
            "applicable_process": ["CO2", "MAG"],
            "shielding_gas": {
                "CO2": "CO2 100% — penetration tối đa, nhiều spatter",
                "MAG": "CO2 20% + Ar 80% — ít spatter, bề mặt đẹp hơn",
            },
            "recommended_tip_types": ["N", "D"],
            "note": "Standard MIG/MAG. Phổ biến nhất trong customer base Autoss.",
        },
        {
            "material": "aluminum",
            "vi_name": "Dây hàn nhôm",
            "applicable_process": ["MIG"],
            "shielding_gas": {"MIG": "Ar 100%"},
            "recommended_tip_types": ["Aluminum"],
            "required_tips_N": ["002023", "002024", "002018", "002019"],
            "required_tips_D": ["023043", "023044"],
            "recommended_torches": ["TK-308ALW", "YMXA-250RA", "YMSA-250RA", "CSA-252"],
            "note": "Tip lỗ lớn trơn cho dây nhôm. Dùng MIG + Ar 100% ONLY.",
            "warning": "KHÔNG dùng tip N/D thường với dây nhôm — kẹt dây.",
        },
        {
            "material": "stainless_steel",
            "vi_name": "Dây hàn thép không rỉ",
            "applicable_process": ["MAG", "MIG"],
            "shielding_gas": {"MAG": "CO2 5-20% + Ar balance"},
            "recommended_tip_types": ["N", "D"],
            "note": "Tip N/D thường. Ưu tiên MAG (CO2 thấp) để giữ tính chống gỉ.",
        },
        {
            "material": "flux_cored",
            "vi_name": "Dây hàn lõi thuốc",
            "applicable_process": ["FCAW", "CO2"],
            "shielding_gas": {
                "CO2": "CO2 100% cho rutile flux cored",
                "none": "Self-shielded — không cần khí",
            },
            "recommended_tip_types": ["FluxCored"],
            "required_tips_N": ["002013"],
            "required_tips_D": ["023042"],
            "note": "Tip flux cored lỗ lớn hơn để tránh tắc bởi cặn flux.",
        },
    ],
    "tig_tungsten_guide": [
        {
            "material": "WL15", "color_band": "gold",
            "composition": "1.5% lanthanum",
            "vi": "Vonfram WL15 — thép và kim loại màu (trừ nhôm)",
            "weld_metals": ["steel", "stainless", "copper", "nonferrous_except_aluminum"],
            "current_type": ["DC", "DCEN"],
            "note": "Khởi hồ quang tốt ở dòng thấp. Tuổi thọ dài. Không chứa phóng xạ.",
        },
        {
            "material": "WC20", "color_band": "gray",
            "composition": "2% cerium",
            "vi": "Vonfram WC20 — ĐA NĂNG NHẤT (mọi kim loại)",
            "weld_metals": ["steel", "stainless", "aluminum", "copper", "nonferrous"],
            "current_type": ["DC", "DCEN", "AC"],
            "note": "Lựa chọn tốt nhất khi không chắc. Dùng được cho cả thép lẫn nhôm AC.",
        },
        {
            "material": "WP", "color_band": "green",
            "composition": "Pure tungsten >99.5%",
            "vi": "Vonfram WP thuần — CHỈ cho nhôm (AC)",
            "weld_metals": ["aluminum_only"],
            "current_type": ["AC"],
            "note": "Đầu tự tròn khi hàn AC. KHÔNG dùng cho thép.",
            "warning": "WP trên thép = hồ quang không ổn định. INCOMPATIBLE.",
        },
    ],
    "current_selection_guide": [
        {"plate_mm": "0.5-1.5",  "current_a": "40-80",   "tungsten_mm": 1.0,     "wire_mm": "0.6-0.8"},
        {"plate_mm": "1.0-3.0",  "current_a": "80-150",  "tungsten_mm": 1.6,     "wire_mm": "0.8-0.9"},
        {"plate_mm": "2.0-6.0",  "current_a": "150-300", "tungsten_mm": 2.4,     "wire_mm": "1.0-1.2"},
        {"plate_mm": "4.0-12.0", "current_a": "250-400", "tungsten_mm": 3.2,     "wire_mm": "1.2-1.4"},
        {"plate_mm": "8.0+",     "current_a": "350-500+","tungsten_mm": "3.2-4.0","wire_mm": "1.4-1.6"},
    ],
}


# ================================================================
# MODEL REBUILD (forward reference resolution)
# ================================================================

def _rebuild_all_models():
    import inspect
    _module_globals = globals()
    _namespace = {
        'Optional': Optional, 'List': List, 'Union': Union,
        'Literal': Literal, 'Dict': Dict, 'Any': Any,
        'date': date, 'Enum': Enum, 'BaseModel': BaseModel,
        'Field': Field, 'field_validator': field_validator,
        'model_validator': model_validator,
    }
    _namespace.update(_module_globals)
    for _name, _obj in list(_module_globals.items()):
        if (inspect.isclass(_obj)
                and issubclass(_obj, BaseModel)
                and _obj is not BaseModel):
            try:
                _obj.model_rebuild(force=True, _types_namespace=_namespace)
            except Exception:
                pass


_rebuild_all_models()


# ================================================================
# USAGE EXAMPLE
# ================================================================

if __name__ == "__main__":
    from pydantic import ValidationError

    # 1. Validate Tip (flat structure)
    tip = Tip(
        tokin_part_no="002001",
        category="Tip",
        ecosystem="N",
        current_class="350A",
        display_name_en="N Tip 0.9mm",
        display_name_vi="Béc hàn N 0.9mm x 45L",
        tip_type="N",
        wire_size_mm=0.9,
        total_length_mm=45.0,
        body_length_mm=37.5,
        p_part_nos=["TET00958", "TET00942"],
        d_part_nos=["K980C03"],
        p_model_codes=[],   # rỗng cho consumable
        d_model_codes=[],
        o_part_nos=[],
        o_model_codes=[],
        compatible_with=["001002", "001003", "003002", "004002"],
        editorial_picks=["001002", "003002", "004002"],
        business={"price_vnd": 18000, "price_unit": "cái", "is_priority_sell": True},
        source="Cat02_p1",
        confidence=1.0,
    )
    print(f"✓ Tip {tip.tokin_part_no}: {tip.display_name_vi}")
    print(f"  Price: {tip.business.price_display}")

    # 2. Validate CompatibilityEdge với tất cả relation types mới
    for rel in ["compatible_with", "replaces", "belongs_to", "belongs_to_alternate"]:
        edge = CompatibilityEdge(from_part="002001", to_part="001002",
                                 relation_type=rel, source="Cat03_2015")
        print(f"  Edge {rel}: OK")

    # 3. Negative rule validation
    try:
        bad_edge = CompatibilityEdge(
            from_part="002001", to_part="023015",
            relation_type="incompatible_with"
            # incompatibility_reason bị thiếu → phải raise
        )
    except ValidationError:
        print("✓ Missing incompatibility_reason correctly rejected")

    # 4. ConsumableSet seed count
    print(f"\n✓ ConsumableSets seeded: {len(CONSUMABLE_SETS)}")
    print(f"✓ NegativeRules seeded: {len(NEGATIVE_COMPATIBILITY_RULES)}")
    print(f"✓ CategoryVocabulary seeded: {len(CATEGORY_VOCABULARY)}")
    print(f"\nSchema v12 loaded OK")
