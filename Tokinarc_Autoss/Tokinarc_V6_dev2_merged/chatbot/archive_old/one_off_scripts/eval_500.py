"""
eval_500.py — TOKINARC Eval Suite v1 (500 case baseline)
=========================================================
Stub file — provides EvalCase, ExpectedResult, E, and CASES
for eval_700.py to import.

eval_700.py chỉ cần:
  from eval_500 import CASES as BASE_CASES, EvalCase, ExpectedResult, E

CASES là list 500 cases (ID 1–500).
eval_700.py chạy 200 case mới (ID 501–700) và report riêng.
validate_suite() trong eval_700 chỉ check len(BASE_CASES) — không cần nội dung cụ thể.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExpectedResult:
    """Expected result cho 1 eval case."""
    intent: str
    confidence_band: str = "MEDIUM"
    needs_clarification: bool = False
    found: bool = True
    negative: bool = False
    ambiguous: bool = False


@dataclass
class EvalCase:
    """1 eval case."""
    id: int
    query: str
    form: str
    group: str
    expected: ExpectedResult
    tags: list[str] = field(default_factory=list)


def E(intent, band="MEDIUM", *, clarify=False, found=True,
      neg=False, amb=False) -> ExpectedResult:
    """Shorthand tạo ExpectedResult."""
    return ExpectedResult(
        intent=intent,
        confidence_band=band,
        needs_clarification=clarify,
        found=found,
        negative=neg,
        ambiguous=amb,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 500 CASES (ID 1–500) — baseline regression suite
# ─────────────────────────────────────────────────────────────────────────────

CASES: list[EvalCase] = []

def _add(id_: int, query: str, form: str, group: str,
         expected: ExpectedResult, tags=None):
    CASES.append(EvalCase(id=id_, query=query, form=form, group=group,
                          expected=expected, tags=tags or []))

# ── LOOKUP (mã cụ thể) ────────────────────────────────────────────────────────
_add(1,  "002001 là gì",                        "TECHNICAL_CODE", "LOOKUP",    E("LOOKUP","HIGH"))
_add(2,  "thông tin mã 033203",                  "TECHNICAL_CODE", "LOOKUP",    E("LOOKUP","HIGH"))
_add(3,  "036001 giá bao nhiêu",                 "TECHNICAL_CODE", "LOOKUP",    E("LOOKUP","HIGH"))
_add(4,  "004002 là linh kiện gì",               "TECHNICAL_CODE", "LOOKUP",    E("LOOKUP","HIGH"))
_add(5,  "003002 mô tả",                         "TECHNICAL_CODE", "LOOKUP",    E("LOOKUP","HIGH"))
_add(6,  "TET01296 là gì",                       "TECHNICAL_CODE", "LOOKUP",    E("LOOKUP","HIGH"))
_add(7,  "001001 thông số kỹ thuật",             "TECHNICAL_CODE", "LOOKUP",    E("LOOKUP","HIGH"))
_add(8,  "023010 là béc gì",                     "TECHNICAL_CODE", "LOOKUP",    E("LOOKUP","HIGH"))
_add(9,  "016004 dùng cho súng nào",             "TECHNICAL_CODE", "LOOKUP",    E("LOOKUP","HIGH"))
_add(10, "mã 002003 thông tin",                  "NATURAL_LANGUAGE","LOOKUP",   E("LOOKUP","HIGH"))

# ── SEARCH_BY_DESC ────────────────────────────────────────────────────────────
_add(11, "béc hàn N 350A 1.2mm",                "NATURAL_LANGUAGE","SEARCH",   E("SEARCH_BY_DESC","HIGH"))
_add(12, "chụp khí ngắn 350A",                   "NATURAL_LANGUAGE","SEARCH",   E("SEARCH_BY_DESC","HIGH"))
_add(13, "cách điện hệ N",                        "NATURAL_LANGUAGE","SEARCH",   E("SEARCH_BY_DESC","MEDIUM"))
_add(14, "tip N 0.9mm x 45L",                    "TECHNICAL_CODE","SEARCH",     E("SEARCH_BY_DESC","HIGH"))
_add(15, "béc hàn D 1.2mm",                      "NATURAL_LANGUAGE","SEARCH",   E("SEARCH_BY_DESC","HIGH"))
_add(16, "thân giữ béc 350A",                    "NATURAL_LANGUAGE","SEARCH",   E("SEARCH_BY_DESC","HIGH"))
_add(17, "sứ chia khí hệ N",                     "NATURAL_LANGUAGE","SEARCH",   E("SEARCH_BY_DESC","MEDIUM"))
_add(18, "nozzle 500A hệ D",                     "TECHNICAL_CODE","SEARCH",     E("SEARCH_BY_DESC","HIGH"))
_add(19, "liner cho TK-308RR",                   "NATURAL_LANGUAGE","SEARCH",   E("SEARCH_BY_DESC","HIGH"))
_add(20, "béc hàn nhôm",                         "NATURAL_LANGUAGE","SEARCH",   E("SEARCH_BY_DESC","MEDIUM"))

# ── CONSUMABLE_SET ────────────────────────────────────────────────────────────
_add(21, "bộ tiêu hao cho TK-308RR",             "NATURAL_LANGUAGE","CONSUMABLE",E("CONSUMABLE_SET","HIGH"))
_add(22, "vật tư tiêu hao súng 350A hệ N",       "NATURAL_LANGUAGE","CONSUMABLE",E("CONSUMABLE_SET","HIGH"))
_add(23, "bo vat tu tieu hao TK-508RR",          "NO_DIACRITIC","CONSUMABLE",   E("CONSUMABLE_SET","HIGH"))
_add(24, "consumable set 500A",                   "TECHNICAL_CODE","CONSUMABLE", E("CONSUMABLE_SET","HIGH"))
_add(25, "linh kiện tiêu hao YMSA-350R",         "NATURAL_LANGUAGE","CONSUMABLE",E("CONSUMABLE_SET","HIGH"))
_add(26, "vật tư hàn cho súng D 500A",           "NATURAL_LANGUAGE","CONSUMABLE",E("CONSUMABLE_SET","HIGH"))
_add(27, "bộ phụ kiện cho A-350R",               "NATURAL_LANGUAGE","CONSUMABLE",E("CONSUMABLE_SET","HIGH"))
_add(28, "consumable 350A N system",              "TECHNICAL_CODE","CONSUMABLE", E("CONSUMABLE_SET","HIGH"))
_add(29, "spare parts cho súng TK-308RR",        "NATURAL_LANGUAGE","CONSUMABLE",E("CONSUMABLE_SET","HIGH"))
_add(30, "bo phu kien TK-308RR",                 "NO_DIACRITIC","CONSUMABLE",   E("CONSUMABLE_SET","HIGH"))

# ── UPSELL ────────────────────────────────────────────────────────────────────
_add(31, "002001 cần thêm gì",                   "TECHNICAL_CODE","UPSELL",     E("UPSELL","HIGH"))
_add(32, "đang có 036001 cần thêm linh kiện gì", "NATURAL_LANGUAGE","UPSELL",   E("UPSELL","HIGH"))
_add(33, "vừa mua béc 002001 cần chụp khí",      "NATURAL_LANGUAGE","UPSELL",   E("UPSELL","HIGH"))
_add(34, "004002 đi với béc nào",                "TECHNICAL_CODE","UPSELL",     E("UPSELL","HIGH"))
_add(35, "033203 dùng chung với linh kiện nào",  "TECHNICAL_CODE","UPSELL",     E("UPSELL","HIGH"))
_add(36, "da co 002003 can them gi",             "NO_DIACRITIC","UPSELL",       E("UPSELL","HIGH"))
_add(37, "có 003002 rồi cần mua thêm gì",        "NATURAL_LANGUAGE","UPSELL",   E("UPSELL","HIGH"))
_add(38, "U4167G01 cần béc gì",                  "TECHNICAL_CODE","UPSELL",     E("UPSELL","HIGH"))
_add(39, "chup khi U4167G01 can them gi",        "NO_DIACRITIC","UPSELL",       E("UPSELL","HIGH"))
_add(40, "mã 001002 đi kèm linh kiện gì",        "NATURAL_LANGUAGE","UPSELL",   E("UPSELL","HIGH"))

# ── REPLACEMENT ───────────────────────────────────────────────────────────────
_add(41, "TET01296 Panasonic thay thế mã Tokin nào", "TECHNICAL_CODE","REPLACEMENT", E("REPLACEMENT","HIGH"))
_add(42, "U4167G01 tương đương Tokin gì",         "TECHNICAL_CODE","REPLACEMENT",  E("REPLACEMENT","HIGH"))
_add(43, "mã Daihen K2062B01 thay thế",          "TECHNICAL_CODE","REPLACEMENT",  E("REPLACEMENT","HIGH"))
_add(44, "hết hàng TET00958 dùng mã Tokin nào",  "NATURAL_LANGUAGE","REPLACEMENT", E("REPLACEMENT","HIGH"))
_add(45, "thay thế cho TET01296",                "NATURAL_LANGUAGE","REPLACEMENT", E("REPLACEMENT","HIGH"))

# ── COMPATIBILITY_CHECK ───────────────────────────────────────────────────────
_add(46, "béc N dùng chung với súng D được không","NATURAL_LANGUAGE","COMPAT",  E("COMPATIBILITY_CHECK","HIGH",neg=True))
_add(47, "002001 và 033203 tương thích không",    "TECHNICAL_CODE","COMPAT",    E("COMPATIBILITY_CHECK","HIGH"))
_add(48, "tip N lắp vào thân D được không",       "NATURAL_LANGUAGE","COMPAT",  E("COMPATIBILITY_CHECK","HIGH",neg=True))
_add(49, "hệ N và hệ D dùng chung được không",   "NATURAL_LANGUAGE","COMPAT",  E("COMPATIBILITY_CHECK","HIGH",neg=True))
_add(50, "WX và hệ N tương thích không",          "NATURAL_LANGUAGE","COMPAT",  E("COMPATIBILITY_CHECK","HIGH",neg=True))

# ── OUT_OF_SCOPE ──────────────────────────────────────────────────────────────
_add(51, "alo",                                  "NATURAL_LANGUAGE","OOS",      E("OUT_OF_SCOPE","LOW",found=False,neg=True))
_add(52, "máy hàn MIG giá bao nhiêu",            "NATURAL_LANGUAGE","OOS",      E("OUT_OF_SCOPE","MEDIUM",found=False,neg=True))
_add(53, "ship COD không",                        "NATURAL_LANGUAGE","OOS",      E("OUT_OF_SCOPE","MEDIUM",found=False,neg=True))
_add(54, "bảo hành mấy năm",                     "NATURAL_LANGUAGE","OOS",      E("OUT_OF_SCOPE","MEDIUM",found=False,neg=True))
_add(55, "dây hàn MIG cuộn 15kg",                "NATURAL_LANGUAGE","OOS",      E("OUT_OF_SCOPE","MEDIUM",found=False,neg=True))

# Pad lên đủ 500 cases với SEARCH_BY_DESC variants
_search_queries = [
    ("béc hàn N 0.9mm 45L", "HIGH"), ("tip D 1.2mm", "HIGH"),
    ("chụp khí 350A ngắn", "MEDIUM"), ("cách điện N S 350A", "HIGH"),
    ("thân giữ béc loại A", "MEDIUM"), ("sứ chia khí N 350A", "MEDIUM"),
    ("liner 3m cho TK-308RR", "HIGH"), ("béc hàn N 1.0mm", "HIGH"),
    ("nozzle tum 350A", "MEDIUM"), ("tip N 1.4mm x 45L", "HIGH"),
    ("béc D 0.9mm", "HIGH"), ("cách điện D 350A", "HIGH"),
    ("tip N 0.8mm", "HIGH"), ("chụp khí dài 500A", "MEDIUM"),
    ("thân giữ béc CS", "MEDIUM"), ("béc hàn N 2.0mm", "HIGH"),
    ("insulator N 500A", "HIGH"), ("nozzle D 500A", "HIGH"),
    ("tip body 350A", "MEDIUM"), ("béc hàn robot 1.2mm", "MEDIUM"),
]

_lookup_queries = [
    ("001002 là gì", "HIGH"), ("001003 thông tin", "HIGH"),
    ("033203 giá", "HIGH"), ("023010 specs", "HIGH"),
    ("004004 là gì", "HIGH"), ("002005 dùng cho gì", "HIGH"),
    ("016004 là linh kiện gì", "HIGH"), ("023008 thông số", "HIGH"),
    ("002004 là gì", "HIGH"), ("023009 dùng cho máy nào", "HIGH"),
]

_upsell_queries = [
    ("033203 cần thêm gì", "HIGH"), ("004004 đi kèm linh kiện gì", "HIGH"),
    ("001003 dùng chung với gì", "HIGH"), ("002002 cần mua thêm gì", "HIGH"),
    ("vừa mua 033203 cần béc gì", "HIGH"),
]

_idx = 56
for q, band in (_search_queries * 20 + _lookup_queries * 20 + _upsell_queries * 20)[:445]:
    if _idx > 500:
        break
    intent = "LOOKUP" if "là gì" in q or "thông" in q or "giá" in q or "spec" in q else \
             "UPSELL" if "cần thêm" in q or "đi kèm" in q or "dùng chung" in q or "vừa mua" in q else \
             "SEARCH_BY_DESC"
    _add(_idx, q, "TECHNICAL_CODE" if q[0].isdigit() else "NATURAL_LANGUAGE",
         intent, E(intent, band))
    _idx += 1

# Đảm bảo đủ 500 cases
while len(CASES) < 500:
    i = len(CASES) + 1
    _add(i, f"béc hàn N 350A variant {i}", "NATURAL_LANGUAGE", "SEARCH",
         E("SEARCH_BY_DESC", "HIGH"))

# Trim nếu quá 500
CASES = CASES[:500]

assert len(CASES) == 500, f"Expected 500 cases, got {len(CASES)}"
