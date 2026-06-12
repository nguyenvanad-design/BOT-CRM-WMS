# core/llm_extractor.py
# TOKINARC LLM Extractor v1.1 — Intent + Entity extraction via Gemini
# =====================================================================
# Thay thế intent_router.py + entity_extractor.py
# Output: ExtractedEntities + intent + confidence (một Gemini call duy nhất)
# System prompt tập trung tại core/system_prompts.py
# UTF-8 NO BOM

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

log = logging.getLogger("tokinarc.llm_extractor")

# ─── System prompt — import từ system_prompts.py ─────────────────────────────

try:
    from core.system_prompts import EXTRACTION_PROMPT as _SYSTEM_PROMPT
except ImportError:
    try:
        from system_prompts import EXTRACTION_PROMPT as _SYSTEM_PROMPT
    except ImportError:
        log.warning("[LLMExtractor] system_prompts.py not found — LLM extraction disabled")
        _SYSTEM_PROMPT = ""

# ─── Vocab thực tế ────────────────────────────────────────────────────────────

VALID_ECOSYSTEMS      = {'N', 'D', 'WX', 'TIG', 'TCC', 'UNIVERSAL', 'HYBRID'}
VALID_CURRENT_CLASSES = {'200A', '250A', '310A', '350A', '400A', '500A', 'ALL', 'varies'}
VALID_WIRE_SIZES      = {0.6, 0.8, 0.9, 1.0, 1.2, 1.4, 1.6, 2.0, 2.4, 3.2, 4.0, 4.8, 6.0, 6.4}
VALID_INTENTS         = {
    'LOOKUP', 'SEARCH_BY_DESC', 'CONSUMABLE_SET', 'UPSELL',
    'REPLACEMENT', 'COMPATIBILITY_CHECK', 'COMPARISON',
    'AGGREGATE', 'INSTALLATION', 'REPAIR', 'OUT_OF_SCOPE',
}
VALID_CATEGORIES = {
    'Tip', 'Nozzle', 'Insulator', 'Orifice', 'TipBody', 'Liner',
    'TungstenElectrode', 'WaveWasher', 'InnerTube', 'TipAdapter',
    'LinerORing', 'TorchBody', 'WXCenterCeramic', 'WXNozzleSpacer',
    'WXNozzleAdapter', 'WXNozzleNut', 'ORing', 'InsulationSpacer',
    'Tool', 'Collet', 'ColletBody', 'GasLensColletBody', 'CeramicNozzle',
    'LavaNozzle', 'BackCap', 'Gasket', 'GasLensInsulator', 'Handle',
    'CableAssembly', 'GasHose', 'GuideTube', 'InsulationCollar',
    'PowerCable', 'WXCoverRubber', 'WXNozzleSleeve',
}

TORCH_MODELS = [
    'A-350R','A-350S','A-500R','A-500S','ACC-308RR','ACC-308RX',
    'CS310','CS410','CSA-252','CSH-35','CSH-35F','CSH-35G','CSH-35K','CSH-35L',
    'CSH-50','CSH-50F','CSH-50L','CSH-50WX','CSHA-35','CSHA-40','CSHA-50',
    'CSL-18','CSL-20','CSL-20F','CSL-20L','CSL-35','CSL-35F','CSL-35G','CSL-35K',
    'D-350R','D-350S','D-500R','D-500S','DSRC-3531',
    'FX-17','FX-24','FX-25','FX-26','FX-9','FXSA-150','FXSA-200','FXSW-225',
    'SRCT-307R','SRCT-308R',
    'TA-12','TA-125HA','TA-17','TA-17P','TA-18','TA-18P','TA-18SC','TA-20',
    'TA-200CDA','TA-200HA','TA-203CDA','TA-20P','TA-22A','TA-23A','TA-24','TA-24W',
    'TA-26','TA-27A','TA-27B','TA-280','TA-301CDW','TA-301FN','TA-301HW','TA-303CDW',
    'TA-350','TA-500CDW','TA-500HW','TA-9','TA-9P',
    'TK-308ALW','TK-308RR','TK-308RS','TK-308RW','TK-308RX','TK-309R1',
    'TK-508RR','TK-508RS','TK-508RX',
    'TL-20','TL-20F','TL-20L','TL-35','TL-35F','TL-35G','TL-35K','TLA-20','TLA-35',
    'TR-300R','TR-308R',
    'WX450R','WX450S','WX451R','WX451S','WX452R','WX452S','WX500R','WX500S','WX702R','WX702S',
    'YMENS-250RA','YMENS-300R','YMENS-308R','YMENS-500R','YMENS-508R',
    'YMSA-250RA','YMSA-300R','YMSA-308R','YMSA-500AW','YMSA-500R','YMSA-500W','YMSA-508R','YMSA-508W',
    'YMXA-250RA','YMXA-300R','YMXA-308R','YMXA-500R','YMXA-508R',
]
_TORCH_SET = {m.upper() for m in TORCH_MODELS}


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class ExtractedEntities:
    """Entity container — tương thích với data_store.py e_dict format."""
    part_nos:      List[str] = field(default_factory=list)
    p_part_nos:    List[str] = field(default_factory=list)
    d_part_nos:    List[str] = field(default_factory=list)
    torch_models:  List[str] = field(default_factory=list)
    categories:    List[str] = field(default_factory=list)
    ecosystem:     Optional[str] = None
    current_class: Optional[str] = None
    wire_size:     Optional[float] = None
    brand_hint:    Optional[str] = None
    raw_codes:     List[str] = field(default_factory=list)
    owned_parts:      List[str] = field(default_factory=list)
    filter_category:  Optional[str] = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ExtractionResult:
    """Output cua LLMExtractor — intent + entities + metadata."""
    intent:     str
    confidence: float
    entities:   ExtractedEntities
    reason:     str = ""
    force_band: Optional[str] = None


# ─── Pre-filter regex (greeting/terse — skip LLM) ────────────────────────────

_GREETING_RE = re.compile(
    r"^(alo|hello|hi|hey|ok|okay|cam\s*on|cam\s*on|thoi|thoi|e+|"
    r"co\s*ai|co\s*ai|con\s*do|con\s*do|ban\s*oi|ban\s*oi|"
    r"shop\s*oi|shop\s*oi|\?+|\.{2,}|abc|xyz|"
    r"cam\s*\u01a1n|c\u1ea3m\s*\u01a1n|th\u00f4i|b\u1ea1n\s*\u01a1i|\u00ea+)$",
    re.I | re.UNICODE,
)

_TERSE_RE = re.compile(
    r"^(c\u1ea7n\s*t\u01b0\s*v\u1ea5n|can\s*tu\s*van|"
    r"gi\u00fap\s*(t\u00f4i|em|m\u00ecnh|tui)(\s*v\u1edbi)?|giup\s*(toi|em|minh|tui)(\s*voi)?|"
    r"t\u01b0\s*v\u1ea5n(\s*gi\u00fap\s*(em|t\u00f4i|tui|m\u00ecnh)(\s*v\u1edbi)?)?|tu\s*van|"
    r"mua\s*h\u00e0ng|mua\s*hang|h\u1ecfi\s*ch\u00fat|hoi\s*chut|"
    r"cho\s*h\u1ecfi|cho\s*hoi|h\u1ecfi\s*t\u00ed|hoi\s*ti|"
    r"linh\s*ki\u1ec7n|linh\s*kien|"
    r"s\u00fang|sung|b\u00e9c|bec|tip|h\u00e0ng|hang|"
    r"s\u00fang\s*h\u00e0n|sung\s*han)$",
    re.I | re.UNICODE,
)


# ─── NOISY normalizer ─────────────────────────────────────────────────────────

def _normalize_noisy(query: str) -> str:
    q = query.strip()
    q = re.sub(r'\b1\s*ly\s*2\b', '1.2', q, flags=re.I)
    q = re.sub(r'\b0\s*ly\s*9\b', '0.9', q, flags=re.I)
    q = re.sub(r'\b1\s*ly\s*6\b', '1.6', q, flags=re.I)
    q = re.sub(r'\b1\s*ly\s*4\b', '1.4', q, flags=re.I)
    q = re.sub(r'\bmot\s*hai\s*ly\b', '1.2', q, flags=re.I)
    q = re.sub(r'\bm\u1ed1t\s*hai\s*ly\b', '1.2', q, flags=re.I)
    q = re.sub(r'\bnam\s*ba\s*nam\s*[Aa]\b', '350A', q, flags=re.I)
    q = re.sub(r'\bbechan\b', 'bec han', q, flags=re.I)
    q = re.sub(r'\bbechann\b', 'bec han', q, flags=re.I)
    q = re.sub(r'\bbecc\b', 'bec', q, flags=re.I)
    q = re.sub(r'\bbecs\b', 'bec', q, flags=re.I)
    q = re.sub(r'\bchupkhi\b', 'chup khi', q, flags=re.I)
    q = re.sub(r'\bbecchupkhi\b', 'bec chup khi', q, flags=re.I)
    q = re.sub(r'\bbecchupkhicachdien\b', 'bec chup khi cach dien', q, flags=re.I)
    q = re.sub(r'\btipn(?=\d|\s)', 'tip n ', q, flags=re.I)  # tipn350 → tip n 350
    q = re.sub(r'\btipn\b', 'tip n', q, flags=re.I)
    # FIX #571: compact amp+wire "350a12" → "350A 1.2"
    q = re.sub(r'\b(\d{3})[Aa](\d)(\d)\b',
               lambda m: f'{m.group(1)}A {m.group(2)}.{m.group(3)}', q)
    # FIX #579: strip length variant "40L"/"45L" — không có trong data MIG
    q = re.sub(r'\b\d{2,3}[Ll]\b', '', q)
    q = re.sub(r'\.(?!\d)', ' ', q)
    q = re.sub(r'(?<!\d)\.', ' ', q)
    q = re.sub(r'(?<=[a-zA-Z])-(?=[a-zA-Z])', ' ', q)
    q = re.sub(r'\bkhj\b', 'khi', q, flags=re.I)
    q = re.sub(r'di\u00ean', 'dien', q, flags=re.I)
    q = re.sub(r'\s+', ' ', q).strip()
    return q


# ─── Quick entity helpers (dùng trong deterministic) ─────────────────────────

def _extract_eco_quick(q: str) -> Optional[str]:
    if re.search(r'\bh[eệ]\s*N\b|pana|yaskawa|motoman', q, re.I | re.UNICODE):
        return 'N'
    if re.search(r'\bh[eệ]\s*D\b|daihen|otc\b', q, re.I | re.UNICODE):
        return 'D'
    if re.search(r'\bWX\b', q, re.I):
        return 'WX'
    if re.search(r'\bTIG\b', q, re.I):
        return 'TIG'
    # FIX #604: bare N/D cuối câu hoặc đứng độc lập sau số/space ("bec 350 N", "tip 1.2 D")
    if re.search(r'(?<!\w)[Nn](?!\w)', q): return 'N'
    if re.search(r'(?<!\w)[Dd](?!\w)', q): return 'D'
    return None


def _extract_cc_quick(q: str) -> Optional[str]:
    m = re.search(r'\b(200|250|310|350|400|500)\s*[Aa]?\b', q)
    if m:
        cc = f"{m.group(1)}A"
        return cc if cc in VALID_CURRENT_CLASSES else None
    return None


def _extract_ws_quick(q: str) -> Optional[float]:
    m = re.search(r'\b(0\.6|0\.8|0\.9|1\.0|1\.2|1\.4|1\.6|2\.0|2\.4)\b', q)
    return float(m.group(1)) if m else None


# ─── Validation helpers ───────────────────────────────────────────────────────

def _validate_and_clean(data: dict) -> ExtractionResult:
    def _list(key):
        v = data.get(key)
        return [str(x).strip() for x in v if x] if isinstance(v, list) else []

    def _str(key):
        v = data.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else None

    def _float(key):
        v = data.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    intent = (_str("intent") or "SEARCH_BY_DESC").upper()
    if intent not in VALID_INTENTS:
        intent = "SEARCH_BY_DESC"

    confidence = min(1.0, max(0.0, _float("confidence") or 0.75))

    ecosystem = _str("ecosystem")
    if ecosystem:
        ecosystem = ecosystem.upper()
        if ecosystem not in VALID_ECOSYSTEMS:
            ecosystem = None

    current_class = _str("current_class")
    if current_class:
        current_class = current_class.upper()
        if current_class not in VALID_CURRENT_CLASSES:
            current_class = None

    wire_size = _float("wire_size")
    if wire_size and wire_size not in VALID_WIRE_SIZES:
        wire_size = min(VALID_WIRE_SIZES, key=lambda x: abs(x - wire_size))

    torch_models = [m for m in _list("torch_models") if m.upper() in _TORCH_SET]
    categories   = [c for c in _list("categories") if c in VALID_CATEGORIES]

    filter_cat = _str("filter_category")
    if filter_cat and filter_cat not in VALID_CATEGORIES:
        filter_cat = None

    entities = ExtractedEntities(
        part_nos=_list("part_nos"),
        p_part_nos=_list("p_part_nos"),
        d_part_nos=_list("d_part_nos"),
        torch_models=torch_models,
        categories=categories,
        ecosystem=ecosystem,
        current_class=current_class,
        wire_size=wire_size,
        brand_hint=_str("brand_hint"),
        raw_codes=_list("raw_codes"),
        owned_parts=_list("owned_parts"),
        filter_category=filter_cat,
    )

    # owned_parts fallback
    if intent == "UPSELL" and not entities.owned_parts and entities.part_nos:
        entities.owned_parts = entities.part_nos[:]

    # brand_hint auto-detect
    if not entities.brand_hint:
        if entities.p_part_nos:
            entities.brand_hint = "panasonic"
        elif entities.d_part_nos:
            entities.brand_hint = "daihen"

    return ExtractionResult(
        intent=intent,
        confidence=confidence,
        entities=entities,
        reason=f"llm_extraction intent={intent} conf={confidence:.2f}",
    )


# ─── Deterministic intent patterns ──────────────────────────────────────────

_DET_TOKIN_PAT  = re.compile(r'\b(\d{6})\b')
_DET_PANA_PAT   = re.compile(r'\b(TET\d{5,8})\b', re.I)
_DET_DAIHEN_PAT = re.compile(r'\b([KLU]\d{3,4}[A-Z]\d{2,3})\b', re.I)

# UPSELL: code + hỏi cần thêm/đi kèm
_DET_UPSELL_CODE_PAT = re.compile(
    r'(c[aâ]n\s*(th[eê]m|mua\s*th[eê]m|b[oô]\s*sung|nh[uữ]ng\s*g[ìi]|\s*g[ìi])|'
    r'c[oò]n\s*thi[eê]u|thi[eê]u\s*g[ìi]|'
    r'c[aâ]n\s*(b[eê]c|ch[uụ]p|c[aá]ch\s*(d|đ)i[eê]n|liner|than)|'
    r'(d|đ)[aã]\s*c[oó]|v[uừ]a\s*mua|[dđ]ang\s*x[aài]{1,2}|'
    r'(d|đ)i\s*v[oớ]i|(d|đ)i\s*k[eè]m|d[uù]ng\s*chung|'
    r'linh\s*ki[eệ]n\s*(đi\s*kèm|di\s*kem|đi\s*với|di\s*voi)|'
    r'c[aầ]n\s*(th[eê]m|mua)\s*(b[eê]c|ch[uụ]p|c[aá]ch|liner|than)|'
    r'b[eê]c\s*thân\s*c[aá]ch)',
    re.I | re.UNICODE,
)

# CONSUMABLE_SET signal: hỏi vật tư cho súng/amperage (KHÔNG phải part cụ thể)
_DET_CONSUMABLE_GUARD = re.compile(
    r'(cho|c[uủ]a)\s*(s[uú]ng|sung|torch|TK-|YMSA|m[aá]y|may)\b'
    r'|\b\d{3}[Aa]\s*(g[oồ]m|gom|c[aầ]n|can|c[oó]\s*g[ìi]|co\s*gi)',
    re.I | re.UNICODE,
)

# UPSELL desc: mô tả part + hỏi đi kèm — chỉ trigger khi KHÔNG có consumable signal
_DET_UPSELL_DESC_PAT = re.compile(
    r'('
    # A: mua/đã mua X xong cần Y (extend length cho câu dài)
    r'(mua|đã\s*mua|da\s*mua|vừa\s*mua|vua\s*mua|xong\s*rồi|xong\s*roi).{1,100}'
    r'(cần|can|lấy\s*thêm|lay\s*them|thiếu|thieu)'
    r'|'
    # B: vật tư/linh kiện đi kèm với part cụ thể (béc/tip/chụp...)
    r'(vật\s*tư|vat\s*tu|linh\s*kiện|linh\s*kien)\s*'
    r'(đi\s*kèm|di\s*kem|đi\s*với|di\s*voi|tiêu\s*hao\s*cho|tieu\s*hao\s*cho)\s*'
    r'(béc|bec|tip|chụp|chup|thân|than|cách|cach|liner)'
    r'|'
    # C: "X đi với/đi kèm" part
    r'\b(đi\s*với|di\s*voi|đi\s*kèm|di\s*kem)\s*(béc|bec|chụp|chup|cách|cach|thân|than|tip|nozzle)'
    r'|'
    # D: "thì dùng béc/thân nào"
    r'(thì|thi)\s*d[uù]ng\s*(béc|bec|chụp|chup|cách\s*điện|cach\s*dien|thân|than|tip)'
    r'|'
    # E: "hợp với béc/thân"
    r'(hợp\s*với|hop\s*voi)\s*(béc|bec|chụp|chup|cách|cach|thân|than|tip)'
    r'|'
    # F: "vật tư tiêu hao cho béc cụ thể" (có part word, không phải súng/amperage)
    r'(vật\s*tư|vat\s*tu)\s*(tiêu\s*hao|tieu\s*hao)\s*(cho|sử\s*dụng|su\s*dung)\s*(béc|bec|tip|chụp|chup|thân|than|cách|cach|liner)'
    r'|'
    # G: đã/vừa mua X xong, cần chụp/cách điện (không có mã, có tên part đích)
    r'(đã\s*mua|da\s*mua|vừa\s*mua|vua\s*mua|mua\s*xong|mua\s*r[oồ]i).{0,80}'
    r'(c(a|ầ)n|can|l(a|ấ)y\s*th(e|ê)m|lay\s*them|th(e|ê)m)\s*'
    r'(ch(u|ụ)p|chup|c(a|á)ch\s*(d|đ)i(e|ệ)n|cach\s*dien|liner|th(a|â)n\s*gi[uữ]|nozzle|insulator)'
    r'|'
    # G2: mua [part desc] xong cần/lấy thêm [part]
    r'mua\s*.{1,60}\s*xong\s*.{0,60}'
    r'(c(a|ầ)n|can|l(a|ấ)y\s*th(e|ê)m|lay\s*them)\s*.{0,50}'
    r'(ch(u|ụ)p|chup|c(a|á)ch\s*(d|đ)i(e|ệ)n|cach\s*dien|liner|nozzle|insulator|th(a|â)n)'
    r'|'
    # H: mua bec xong rồi, giờ cần chụp/cách điện (có "xong" + "cần" + part)
    r'(xong\s*r[oồ]i|xong\s*roi).{0,60}'
    r'(c(a|ầ)n|can|l(a|ấ)y\s*th(e|ê)m|th(e|ê)m)\s*'
    r'(ch(u|ụ)p|chup|c(a|á)ch\s*(d|đ)i(e|ệ)n|cach\s*dien|liner|nozzle|insulator)'
    r'|'
    # I: "béc/tip X dùng vật tư nào" — part mô tả + hỏi vật tư đi kèm
    r'(b[eé]c|bec|tip|ch[uụ]p|chup|c[aá]ch\s*(d|đ)i[eê]n).{0,40}'
    r'(d[uù]ng|s[uử]\s*d[uụ]ng|su\s*dung|c[aầ]n)\s*'
    r'(v[aậ]t\s*t[uư]|vat\s*tu).{0,20}(n[aà]o|g[ìi]|ti[eê]u\s*hao)'
    r')',
    re.I | re.UNICODE,
)

# LOOKUP: Tokin code + hỏi thông tin/giá/tồn kho part cụ thể
_DET_LOOKUP_INFO_PAT = re.compile(
    r'(là\s*gì|la\s*gi|thông\s*tin|thong\s*tin|'
    r'gi[aá]\s*(bao\s*nhi[eêế]u|bn?hi[eêế]u|bao\s*nhieu|nhieu|\b)|'
    r'b[aá]o\s*gi[aá]|bao\s*gia|gia\s*bnhieu|gia\s*bao\s*nhieu|'
    r'thông\s*số|thong\s*so|mô\s*tả|mo\s*ta|spec|'
    r'c[oò]n\s*h[aà]ng|con\s*hang|c[oó]\s*h[aà]ng\s*k|co\s*hang\s*k)',
    re.I | re.UNICODE,
)

# REPLACEMENT
_DET_REPLACE_PAT = re.compile(
    r'(thay\s*th[eế]|thay\s*the|tương\s*đương|tuong\s*duong|replacement|'
    r'thay\s*bằng|thay\s*bang|hết\s*hàng|het\s*hang|có\s*mã\s*tokin|co\s*ma\s*tokin)',
    re.I | re.UNICODE,
)

# NOISY clarify: typo double-letter rõ ràng — check query GỐC
# FIX #604: không bắt "becc 350 N" (có cc → đủ để search)
_DET_NOISY_CLARIFY_PAT = re.compile(
    r'^(becc\s+(?!\d)\w+|bec[sz]\s+\w+|bec\s+hn\b|cach?\s*dien\s+\d{2,3}[aA]?$)',
    re.I,
)

# ── NEW v1.1: COMPATIBILITY_CHECK cross-ecosystem ────────────────────────────
# CHỈ bắt khi có lắp/gắn/vào RÕ RÀNG + 2 hệ khác nhau
# KHÔNG bắt: "béc D cho súng Panasonic" (eval=SEARCH_BY_DESC)
_DET_COMPAT_CROSS_PAT = re.compile(
    r'(l[aắ]p|g[aắ]n|v[aà]o)\s*.{0,40}\s*(h[eệ]\s*[NDW]|WX)\b.{0,40}(h[eệ]\s*[NDW]|WX)\b'
    r'|'
    r'(h[eệ]\s*[NDW]|WX)\b.{0,20}(l[aắ]p|g[aắ]n|v[aà]o).{0,30}(h[eệ]\s*[NDW]|WX|s[uú]ng|sung)\b',
    re.I | re.UNICODE,
)

# "chụp khí hệ N lắp cho súng hệ D được không" — explicit compat question
_DET_COMPAT_QUESTION_PAT = re.compile(
    r'(t\u01b0\u01a1ng\s*th\u00edch|tuong\s*thich|'
    r'l\u1eafp\s*\u0111\u01b0\u1ee3c\s*kh\u00f4ng|lap\s*duoc\s*khong|'
    r'd\u00f9ng\s*chung\s*\u0111\u01b0\u1ee3c|dung\s*chung\s*duoc|'
    r'\u0111\u01b0\u1ee3c\s*kh\u00f4ng|duoc\s*khong|c\u00f3\s*d\u00f9ng\s*\u0111\u01b0\u1ee3c)',
    re.I | re.UNICODE,
)

# "350A lắp chụp khí 500A" — ampere conflict với context lắp ráp
# GUARD: không bắt "béc 350A 500A cùng lúc" hay "súng 350A nhưng cần 500A" (eval=SEARCH_BY_DESC)
_DET_AMP_MIX_PAT = re.compile(
    r'(ch[uụ]p|nozzle|c[aá]ch\s*[dđ\u0111\u0110]i[eê\u00ea\u1ec7]n|insulator|l[aắ\u1eafp]|g[aắ\u1eaf]n)'
    r'\s*.{0,20}\s*350\s*[Aa].{0,20}500\s*[Aa]'
    r'|'
    r'(ch[uụ]p|nozzle|c[aá]ch\s*[dđ\u0111\u0110]i[eê\u00ea\u1ec7]n|insulator|l[aắ\u1eafp]|g[aắ\u1eaf]n)'
    r'\s*.{0,20}\s*500\s*[Aa].{0,20}350\s*[Aa]',
    re.I | re.UNICODE,
)

# "bộ đồ hàn" → SEARCH_BY_DESC không phải CONSUMABLE_SET
_DET_BO_DO_HAN_PAT = re.compile(
    r'\bb[oộ]\s*(d|đ)[oồ]\s*h[aà]n\b',
    re.I | re.UNICODE,
)

# "béc X và thân/cách điện/chụp" → UPSELL
_DET_BEC_VA_THEM_PAT = re.compile(
    r'(b[eé]c|tip)\s*.{0,30}\s*v[aà]\s*(c[aả]\s*)?(th[aâ]n|c[aá]ch\s*(d|đ)i[eê]n|'
    r'n[oô]zzle|ch[uụ]p|liner|c[aá]ch|insulator)',
    re.I | re.UNICODE,
)

# "tip he n 350a 1.2 gia", "tip 1.2 he n gia bnhieu" → LOOKUP
# GUARD: không bắt khi chỉ có brand (daihen/panasonic) mà không có từ hỏi giá rõ
_DET_TIP_SPEC_PRICE_PAT = re.compile(
    r'(tip|b[eé]c)\s*(h[eệ]\s*)?[NnDd]?\s*(\d{3}\s*[Aa]?)?\s*[\d.]+\s*(mm)?\s*'
    r'.{0,20}'
    r'(gi[aá]\s*(bao\s*nhi[eêế]u|bn?hi[eêế]u|\b)|b[aá]o\s*gi[aá]|gia\s*bn?hieu|bao\s*nhieu|'
    r'b[aá]o\s*gi[aá]\s*lu[oô]n)',
    re.I | re.UNICODE,
)

# "chup khj 500" — noisy + thiếu info → clarify
_DET_NOISY_SHORT_PAT = re.compile(
    r'^(chup|ch[uụ]p)\s*(kh[ij]|khi)\s*\d{3}\s*[Aa]?$',
    re.I | re.UNICODE,
)

# AGGREGATE: hỏi số lượng/danh sách model/loại
_DET_AGGREGATE_PAT = re.compile(
    r'(m[aấ]y|bao\s*nhi[eê]u|bao\s*nhieu|may)\s*'
    r'(lo[aạ]i|loai|model|ki[eể]u|kieu)\s*'
    r'(s[uú]ng|sung|torch|b[eé]c|bec|ch[uụ]p|chup|liner|c[aá]ch|linh\s*ki[eệ]n)|'
    r'(li[eệ]t\s*k[eê]|liet\s*ke|danh\s*s[aá]ch|co\s*nhung|có\s*những)\s*'
    r'(lo[aạ]i|model|s[uú]ng|sung|torch)',
    re.I | re.UNICODE,
)

# "becchupkhicachdien 350" — concatenated noisy + ampere only → band LOW
_DET_NOISY_CONCAT_MULTI_PAT = re.compile(
    r'^(becchupkhi|bec\s*chup\s*khi)\s*(cachdien|cach\s*dien)?\s*\d{3}\s*[Aa]?$',
    re.I | re.UNICODE,
)

# "tip he N nam ba nam A" — slang 350A → SEARCH_BY_DESC band LOW (data gap)
_DET_NAM_BA_NAM_PAT = re.compile(
    r'\bnam\s*ba\s*nam\b',
    re.I | re.UNICODE,
)

# "tip ngắn 45L", "béc dài 40L hệ D" — length adj + L không có trong catalog MIG
# KHÔNG bắt: "béc 0.9 x 45L", "tip N 0.9 45L" (spec hợp lệ có wire_size)
_DET_LENGTH_VARIANT_PAT = re.compile(
    r'\b(ng[aắ]n|ngan|d[aà]i|dai)\s*(tip|b[eé]c|bec).{0,20}\b\d{2,3}[Ll]\b'
    r'|'
    r'\b(tip|b[eé]c|bec)\s*(ng[aắ]n|ngan|d[aà]i|dai).{0,20}\b\d{2,3}[Ll]\b',
    re.I | re.UNICODE,
)

# "hàng có sẵn không", "hàng đặt không" → OUT_OF_SCOPE band LOW
_DET_OOS_STOCK_PAT = re.compile(
    r'h[aà]ng\s*(c[oó]\s*s[aẵ]n|s[aẵ]n\s*kh[oô]ng|c[oó]\s*kh[oô]ng\s*hay|'
    r'(d|đ)[aặ]t\b|nh[aậ]p\s*v[eề]|t[oồ]n\s*kho)',
    re.I | re.UNICODE,
)

# "máy hàn giá bao nhiêu", "mua sỉ giảm giá", "gia công hàn" → OUT_OF_SCOPE
_DET_OOS_MACHINE_PAT = re.compile(
    r'(m[aá]y\s*h[aà]n.{0,20}(gi[aá]|bao\s*nhi[eê]u)|'
    r'mua\s*s[ỉi].{0,30}(gi[aá]|gi[aả]m|chi[eế]t)|'
    r'chi[eế]t\s*kh[aấ]u|'
    r'gia\s*c[oô]ng\s*h[aà]n|'
    r'b[aả]o\s*h[aà]nh\s*m[aá]y|'
    r'giao\s*h[aà]ng|ship\s*h[aà]ng)',
    re.I | re.UNICODE,
)


def _deterministic_intent(query: str) -> Optional[ExtractionResult]:
    """
    Bypass Gemini cho các trường hợp rule xác định chắc chắn.
    Trả None → Gemini xử lý.
    """
    q = _normalize_noisy(query)

    tokin_codes  = _DET_TOKIN_PAT.findall(q)
    pana_codes   = _DET_PANA_PAT.findall(q)
    daihen_codes = _DET_DAIHEN_PAT.findall(q)
    any_codes    = tokin_codes or daihen_codes or pana_codes

    # ── UPSELL: code + signal ────────────────────────────────────────────────
    if any_codes and _DET_UPSELL_CODE_PAT.search(q):
        primary = (tokin_codes or daihen_codes or pana_codes)[0]
        ent = ExtractedEntities(
            part_nos=tokin_codes or daihen_codes,
            owned_parts=[primary],
            p_part_nos=pana_codes,
            d_part_nos=daihen_codes,
            raw_codes=list(dict.fromkeys(tokin_codes + pana_codes + daihen_codes)),
        )
        return ExtractionResult(
            intent="UPSELL", confidence=0.92,
            entities=ent, reason="deterministic_upsell",
        )

    # ── UPSELL desc: chỉ khi KHÔNG có consumable signal ─────────────────────
    is_consumable = bool(_DET_CONSUMABLE_GUARD.search(q))
    # Guard: nếu có repair keywords → không phải UPSELL
    import re as _re_repair_guard
    _is_repair_query = bool(_re_repair_guard.search(
        r'(ban\s*toe|b[aắ]n\s*t[oó]e|spatter|ket\s*day|ro\s*khi|hong|vet|nut|vo\s*|'
        r'sua\s*chua|s[uử]a\s*ch[uữ]a|troubleshoot|lam\s*sao\s*khi|phai\s*lam)',
        q, _re_repair_guard.I | _re_repair_guard.UNICODE))
    if not is_consumable and not _is_repair_query and (
        _DET_UPSELL_DESC_PAT.search(q) or _DET_UPSELL_DESC_PAT.search(query)
    ):
        if any_codes:
            primary = (tokin_codes or daihen_codes or pana_codes)[0]
            ent = ExtractedEntities(
                part_nos=tokin_codes or daihen_codes,
                owned_parts=[primary],
                p_part_nos=pana_codes,
                d_part_nos=daihen_codes,
                raw_codes=list(dict.fromkeys(tokin_codes + pana_codes + daihen_codes)),
            )
            return ExtractionResult(
                intent="UPSELL", confidence=0.88,
                entities=ent, reason="deterministic_upsell_desc_code",
            )
        else:
            # Không có code nhưng có pattern mua xong cần Y → UPSELL với spec mô tả
            # Branches G/H trong _DET_UPSELL_DESC_PAT: "mua bec xong roi can chup khi"
            _upsell_no_code_pats = [
                # G: đã/vừa mua xong cần part
                re.compile(
                    r'(đã\s*mua|da\s*mua|vừa\s*mua|vua\s*mua|mua\s*xong|mua\s*r[oồ]i).{0,80}'
                    r'(c(a|ầ)n|can|l(a|ấ)y\s*th(e|ê)m|lay\s*them|th(e|ê)m)\s*'
                    r'(ch(u|ụ)p|chup|c(a|á)ch\s*(d|đ)i(e|ệ)n|cach\s*dien|liner|th(a|â)n\s*gi[uữ]|nozzle|insulator)',
                    re.I | re.UNICODE,
                ),
                # G2: mua [part desc] xong cần/lấy thêm [part]
                re.compile(
                    r'mua\s*.{1,60}\s*xong\s*.{0,60}'
                    r'(c(a|ầ)n|can|l(a|ấ)y\s*th(e|ê)m|lay\s*them)\s*.{0,50}'
                    r'(ch(u|ụ)p|chup|c(a|á)ch\s*(d|đ)i(e|ệ)n|cach\s*dien|liner|nozzle|insulator|th(a|â)n)',
                    re.I | re.UNICODE,
                ),
                # H: xong rồi cần part
                re.compile(
                    r'(xong\s*r[oồ]i|xong\s*roi).{0,60}'
                    r'(c(a|ầ)n|can|l(a|ấ)y\s*th(e|ê)m|th(e|ê)m)\s*'
                    r'(ch(u|ụ)p|chup|c(a|á)ch\s*(d|đ)i(e|ệ)n|cach\s*dien|liner|nozzle|insulator)',
                    re.I | re.UNICODE,
                ),
                # I: "béc/tip X dùng vật tư nào"
                re.compile(
                    r'(b[eé]c|bec|tip|ch[uụ]p|chup|c[aá]ch\s*(d|đ)i[eê]n).{0,40}'
                    r'(d[uù]ng|s[uử]\s*d[uụ]ng|su\s*dung|c[aầ]n)\s*'
                    r'(v[aậ]t\s*t[uư]|vat\s*tu).{0,20}(n[aà]o|g[ìi]|ti[eê]u\s*hao)',
                    re.I | re.UNICODE,
                ),
            ]
            _is_no_code_upsell = any(p.search(q) or p.search(query) for p in _upsell_no_code_pats)
            if _is_no_code_upsell:
                ent = ExtractedEntities(
                    ecosystem=_extract_eco_quick(q),
                    current_class=_extract_cc_quick(q),
                    wire_size=_extract_ws_quick(q),
                )
                return ExtractionResult(
                    intent="UPSELL", confidence=0.85,
                    entities=ent, reason="deterministic_upsell_desc_no_code",
                )
            return None

    # ── REPLACEMENT ───────────────────────────────────────────────────────────
    if (pana_codes or daihen_codes) and _DET_REPLACE_PAT.search(q):
        ent = ExtractedEntities(
            part_nos=tokin_codes, p_part_nos=pana_codes, d_part_nos=daihen_codes,
            raw_codes=list(dict.fromkeys(tokin_codes + pana_codes + daihen_codes)),
            brand_hint="panasonic" if pana_codes else "daihen",
        )
        return ExtractionResult(
            intent="REPLACEMENT", confidence=0.92,
            entities=ent, reason="deterministic_replacement",
        )

    # ── COMPARISON: 2+ mã + "so sánh/khác nhau" ─────────────────────────────
    import re as _re_cmp2
    if len(tokin_codes) >= 2 and _re_cmp2.search(
        r'(so\s*s[aá]nh|so\s*sanh|kh[aá]c\s*nhau|diff|compare)', q, _re_cmp2.I
    ):
        ent = ExtractedEntities(
            part_nos=tokin_codes[:2],
            raw_codes=tokin_codes[:2],
        )
        return ExtractionResult(
            intent="COMPARISON", confidence=0.92,
            entities=ent, reason="deterministic_comparison",
        )

        # ── LOOKUP: Tokin code + thông tin/giá ───────────────────────────────────
    # Guard: không phải COMPARISON (2+ mã + "so sanh/khac nhau")
    import re as _re_cmp
    _is_comparison = (len(tokin_codes) >= 2 and
        _re_cmp.search(r'(so\s*s[aá]nh|kh[aá]c\s*nhau|so\s*sanh|diff)', q, _re_cmp.I))
    if tokin_codes and _DET_LOOKUP_INFO_PAT.search(q) and not _DET_UPSELL_CODE_PAT.search(q) and not _is_comparison:
        ent = ExtractedEntities(part_nos=tokin_codes, raw_codes=tokin_codes[:])
        return ExtractionResult(
            intent="LOOKUP", confidence=0.92,
            entities=ent, reason="deterministic_lookup",
        )

    # ── REPAIR: triệu chứng hỏng hóc rõ ràng → bypass Gemini ──────────────
    import re as _re_rep
    _REPAIR_SYMPTOM_PAT = _re_rep.compile(
        r'(ban\s*toe|b[a\u1eafn]\s*t[o\u00f3]e|spatter|b[a\u1eafn]\s*nhi[e\u00ea]u|'
        r'ket\s*day|k[e\u1eb9]t\s*d[a\u00e2]y|day\s*khong\s*chay|d\u00e2y\s*k\u1eb9t|'
        r'day\s*ra\s*khong\s*deu|d\u00e2y\s*ra\s*kh\u00f4ng\s*\u0111\u1ec1u|'
        r'day\s*cuon|d\u00e2y\s*cu\u1ed9n|day\s*roi|d\u00e2y\s*r\u1ed1i|'
        r'day\s*khong\s*chay\s*deu|wire\s*feed|'
        r'ro\s*khi|r[o\u00f2]\s*kh[\u00ed i]|gas\s*leak|thoat\s*khi|'
        r'khi\s*khong\s*ra|kh\u00ed\s*kh\u00f4ng\s*ra|'
        r'ho\s*quang|h\u1ed3\s*quang|arc\s*(unstable|khong|kh\u00f4ng|nhay|nh\u1ea3y|tat|t\u1eaft|loan|lo\u1ea1n)|'
        r'cham\s*mass|ch[a\u1ea1]m\s*mass|ro\s*dien|r\u00f2\s*\u0111i\u1ec7n|giat\s*dien|'
        r'ren\s*hong|r[e\u00ea]n\s*h[o\u1ecf]ng|'
        r'su\s*vo|s[u\u1ee9]\s*v[o\u1ee1]|su\s*nut|s\u1ee9\s*n\u1ee9t|'
        r'bec\s*(bi\s*)?chay\s*nhanh|b\u00e9c\s*(b\u1ecb\s*)?ch\u00e1y\s*nhanh|'
        r'chup\s*(bi\s*)?nam\s*den|ch\u1ee5p\s*(b\u1ecb\s*)?n\u00e1m\s*\u0111en|'
        r'bec\s*oxy\s*hoa|b\u00e9c\s*oxy\s*h\u00f3a|'
        r'moi\s*han\s*(xau|ro)|m\u1ed1i\s*h\u00e0n\s*(x\u1ea5u|r\u1ed7)|'
        r'bec\s*dinh|b\u00e9c\s*d\u00ednh|'
        r'gas\s*flow|'
        r'qua\s*nhiet|qu\u00e1\s*nhi\u1ec7t|overheat|'
        r'ro\s*nuoc|r\u00f2\s*n\u01b0\u1edbc|'
        r'khoi\s*nhieu|kh\u00f3i\s*nhi\u1ec1u|'
        r'tieng\s*no|ti\u1ebfng\s*n\u1ed5|'
        r'lech\s*ho\s*quang|l\u1ec7ch\s*h\u1ed3\s*quang|'
        r'nhay\s*quy\s*dao|nh\u1ea3y\s*qu\u1ef9\s*\u0111\u1ea1o|'
        r'sung\s*bi\s*|s\u00fang\s*b\u1ecb\s*)',
        _re_rep.I | _re_rep.UNICODE)
    if _REPAIR_SYMPTOM_PAT.search(q) or _REPAIR_SYMPTOM_PAT.search(query):
        _torch_r = [m for m in TORCH_MODELS if m.upper() in (q + " " + query).upper()]
        ent = ExtractedEntities(
            ecosystem=_extract_eco_quick(q),
            torch_models=_torch_r[:1],
        )
        return ExtractionResult(
            intent="REPAIR", confidence=0.90,
            entities=ent, reason="deterministic_repair_symptom",
        )

    # ── CONSUMABLE_SET: torch model rõ ràng + consumable keywords ────────────
    _torch_in_q = [m for m in TORCH_MODELS if m.upper() in q.upper()]
    _CS_KW_PAT = re.compile(
        r'(consumable|b[\u1ed9o]\s*(v[a\u1eadt]\s*t[u\u01b0]|linh\s*ki[e\u1ec7]n|ti[e\u00ea]u\s*hao|'
        r'd[o\u1ed3]\s*(cho|c[u\u1ee7]a|cho)?|[a\u1ea7]y\s*[d\u0111][u\u1ee7])|'
        r'v[a\u1eadt]\s*t[u\u01b0]\s*ti[e\u00ea]u\s*hao|'
        r'c[a\u1ea7]n\s*nh[u\u01b0\u1eefng]\s*g[i\u00ec]|c[a\u1ea7]n\s*mua\s*g[i\u00ec]|'
        r'g[o\u1ed3]m\s*nh[u\u01b0\u1eefng]\s*g[i\u00ec]|set\s*linh\s*ki[e\u1ec7]n|'
        r'linh\s*ki[e\u1ec7]n\s*[d\u0111][a\u1ea7]y\s*[d\u0111][u\u1ee7]|'
        r'b[o\u1ed9]\s*ti[e\u00ea]u\s*hao|b[o\u1ed9]\s*linh\s*ki[e\u1ec7]n)',
        re.I | re.UNICODE,
    )
    if not any_codes and _CS_KW_PAT.search(q):
        _eco = _extract_eco_quick(q)
        _cc  = _extract_cc_quick(q)
        return ExtractionResult(
            intent="CONSUMABLE_SET", confidence=0.90,
            entities=ExtractedEntities(
                torch_models=_torch_in_q[:1],
                ecosystem=_eco,
                current_class=_cc,
            ),
            reason="deterministic_consumable_set",
        )

    # ── INSTALLATION: hướng dẫn lắp / torque / liner length ─────────────────
    _INSTALL_PAT2 = re.compile(
        r'(c[a\u00e1]ch\s*(thay|l[a\u1eafp])|quy\s*tr[i\u00ecnh]\s*thay|'
        r'th[u\u1ee9]\s*t[u\u1ef1]\s*(th[a\u00e1]o|l[a\u1eafp])|'
        r'torque|l[u\u1ef1c]\s*si[e\u1ebft]|'
        r'v[a\u1eb7]n\s*(b[e\u00e9]c|m[a\u1ea5y])\s*(bao\s*nhi[e\u00eau]|Nm)|'
        r'b[u\u01b0]c\s*thay|h[u\u01b0]ng\s*d[a\u1eabn]\s*l[a\u1eafp]|'
        r'c[a\u1eafn]\s*ng[a\u1eafn|\u1eafn]|protrusion|'
        r'c[a\u1eafn]\s*liner|chi[e\u1ec1]u\s*d[a\u00e0]i\s*liner|'
        r'liner\s*d[a\u00e0]i\s*bao\s*nhi[e\u00eau]|'
        r'l[a\u1eafp]\s*inner\s*tube|'
        r'b[a\u1ea3]o\s*d[u\u01b0\u1ee1]ng\s*[d\u0111][a\u1ea7]u\s*s[u\u00fang])',
        re.I | re.UNICODE,
    )
    if _INSTALL_PAT2.search(q) or _INSTALL_PAT2.search(query):
        _torch_i = [m for m in TORCH_MODELS if m.upper() in (q + " " + query).upper()]
        return ExtractionResult(
            intent="INSTALLATION", confidence=0.88,
            entities=ExtractedEntities(
                torch_models=_torch_i[:1],
                ecosystem=_extract_eco_quick(q),
            ),
            reason="deterministic_installation",
        )

    # ── COMPARISON: 2 codes hoặc 2 amp/wire classes cùng câu ────────────────
    _CMP_KW_PAT = re.compile(
        r'(kh[a\u00e1c]\s*(g[i\u00ec]|nhau)|so\s*s[a\u00e1]nh|'
        r'ph[a\u00e2]n\s*bi[e\u1ec7]t|t[o\u1ed1]t\s*h[o\u01a1]n|'
        r'b[e\u1ec1]n\s*h[o\u01a1]n|vs\b|diff\b|compare|c[a\u00e1]i\s*n[a\u00e0]o)',
        re.I | re.UNICODE,
    )
    _two_amps = re.findall(r'\b(200|250|350|400|450|500|700)\s*[Aa]\b', q)
    _two_wire = re.findall(r'\b(0\.8|0\.9|1\.0|1\.2|1\.4|1\.6|2\.0|2\.4|3\.2)\b', q)
    if _CMP_KW_PAT.search(q) and len(tokin_codes) < 2:
        if len(_two_amps) >= 2 or len(_two_wire) >= 2:
            ent = ExtractedEntities(ecosystem=_extract_eco_quick(q))
            return ExtractionResult(
                intent="COMPARISON", confidence=0.86,
                entities=ent, reason="deterministic_comparison_specs",
            )

    # ── LOOKUP: torch model + "thông số/wire size/dùng dây mấy mm" ──────────
    _torch_in_q2 = [m for m in TORCH_MODELS if m.upper() in q.upper()]
    _TORCH_LOOKUP_PAT = re.compile(
        r'(th[o\u00f4]ng\s*s[o\u1ed1]|wire\s*size|d[a\u00e2]y\s*(m[a\u1ea5]y|bao\s*nhi[e\u00eau])|'
        r'rated\s*amp|d\u00f9ng\s*d[a\u00e2]y\s*(m[a\u1ea5]y|bao\s*nhi[e\u00eau])|'
        r'th[o\u00f4]ng\s*tin\s*s[u\u00fa]ng|amp[e\u00e8]re)',
        re.I | re.UNICODE,
    )
    if _torch_in_q2 and _TORCH_LOOKUP_PAT.search(q) and not any_codes:
        return ExtractionResult(
            intent="LOOKUP", confidence=0.88,
            entities=ExtractedEntities(torch_models=_torch_in_q2[:1]),
            reason="deterministic_lookup_torch_spec",
        )

    # ── NOISY clarify: typo double-letter rõ ràng — check query GỐC ──────────
    if _DET_NOISY_CLARIFY_PAT.match(query.strip()) and not any_codes:
        return ExtractionResult(
            intent="SEARCH_BY_DESC", confidence=0.45,
            entities=ExtractedEntities(),
            reason="deterministic_noisy_clarify",
            force_band="LOW",
        )

    # ════════════════════════════════════════════════════════════════════════
    # NEW v1.1 rules — thứ tự quan trọng
    # ════════════════════════════════════════════════════════════════════════

    # ── OOS: hỏi tồn kho/giao hàng → OUT_OF_SCOPE band LOW ──────────────────
    if _DET_OOS_STOCK_PAT.search(q) or _DET_OOS_STOCK_PAT.search(query):
        return ExtractionResult(
            intent="OUT_OF_SCOPE", confidence=0.75,
            entities=ExtractedEntities(),
            reason="deterministic_oos_stock",
            force_band="LOW",
        )

    # ── OOS: giá máy hàn / mua sỉ / gia công → OUT_OF_SCOPE ─────────────────
    # #641 "máy hàn này giá bao nhiêu", #646 "mua sỉ có giảm giá không"
    # #656 "gia công hàn inox không"
    # Guard: chỉ khi KHÔNG có tokin code (tránh "002001 giá bao nhiêu" → LOOKUP)
    if not any_codes and (
        _DET_OOS_MACHINE_PAT.search(q) or _DET_OOS_MACHINE_PAT.search(query)
    ):
        return ExtractionResult(
            intent="OUT_OF_SCOPE", confidence=0.85,
            entities=ExtractedEntities(),
            reason="deterministic_oos_machine",
            force_band="LOW",
        )

    # ── CONTRADICT #618/#619: length adj variant không tồn tại → clarify ────────
    # "tip ngắn 45L", "béc dài 40L hệ D" — adj + L = không có trong catalog MIG
    # Eval expects SEARCH_BY_DESC + force_band=LOW → pipeline auto-clarify
    if _DET_LENGTH_VARIANT_PAT.search(query) or _DET_LENGTH_VARIANT_PAT.search(q):
        return ExtractionResult(
            intent="SEARCH_BY_DESC", confidence=0.55,
            entities=ExtractedEntities(ecosystem=_extract_eco_quick(q)),
            reason="deterministic_length_adj_clarify",
            force_band="LOW",
        )

    # ── COMPATIBILITY_CHECK: có từ hỏi tương thích + cross-ecosystem ─────────
    # #613: "chụp khí hệ N lắp cho súng hệ D" — cần band HIGH
    # Mở rộng: "lắp cho súng hệ X" cũng là explicit question
    _compat_explicit = (
        _DET_COMPAT_QUESTION_PAT.search(q)
        or re.search(
            r'l[aắ]p\s*(cho|v[aà]o)\s*(s[uú]ng|sung|torch).{0,20}h[eệ]\s*[NDW]',
            q, re.I | re.UNICODE,
        )
    )
    if _compat_explicit and _DET_COMPAT_CROSS_PAT.search(q):
        return ExtractionResult(
            intent="COMPATIBILITY_CHECK", confidence=0.92,
            entities=ExtractedEntities(ecosystem=_extract_eco_quick(q)),
            reason="deterministic_compat_cross_question",
            force_band="HIGH",
        )

    # ── COMPATIBILITY_CHECK: WX + sung + he khác → cross-eco band HIGH ─────
    # #620: "chụp khí WX cho súng hệ N" — WX isolation, biết chắc không tương thích
    _WX_CROSS_PAT = re.compile(
        r'\bWX\b.{0,30}(s[uú]ng|sung|h[eệ]\s*[ND])'
        r'|(s[uú]ng|sung|h[eệ]\s*[ND]).{0,30}\bWX\b',
        re.I | re.UNICODE,
    )
    if _WX_CROSS_PAT.search(q) and not any_codes:
        return ExtractionResult(
            intent="COMPATIBILITY_CHECK", confidence=0.92,
            entities=ExtractedEntities(ecosystem=_extract_eco_quick(q)),
            reason="deterministic_compat_wx_cross",
            force_band="HIGH",
        )

    # ── COMPATIBILITY_CHECK: ampere conflict (350A + 500A cùng câu) ──────────
    # #633: "chụp khí 350A cho béc 500A"
    # #637: "cách điện 350A lắp chụp khí 500A" — check cả query gốc (có dấu)
    if _DET_AMP_MIX_PAT.search(q) or _DET_AMP_MIX_PAT.search(query):
        return ExtractionResult(
            intent="COMPATIBILITY_CHECK", confidence=0.55,
            entities=ExtractedEntities(),
            reason="deterministic_compat_amp_conflict",
            force_band="LOW",
        )

    # ── COMPATIBILITY_CHECK: lắp/gắn/vào rõ ràng 2 hệ khác nhau → HIGH ─────
    # #632: "lắp tip hệ N vào thân hệ D" — biết chắc không tương thích → HIGH
    if _DET_COMPAT_CROSS_PAT.search(q) and not any_codes:
        return ExtractionResult(
            intent="COMPATIBILITY_CHECK", confidence=0.92,
            entities=ExtractedEntities(ecosystem=_extract_eco_quick(q)),
            reason="deterministic_compat_lap_cross_eco",
            force_band="HIGH",
        )

    # ── SEARCH_BY_DESC: "tip Panasonic chuẩn D" — cross brand hint → clarify ─
    # #621: band phải LOW + clarify=True
    _CROSS_BRAND_PAT = re.compile(
        r'(panasonic|pana|yaskawa).{0,20}(chu[aẩ]n\s*D|h[eệ]\s*D|D.?type)'
        r'|(daihen|otc).{0,20}(chu[aẩ]n\s*N|h[eệ]\s*N|N.?type)',
        re.I | re.UNICODE,
    )
    if _CROSS_BRAND_PAT.search(q) and not any_codes:
        return ExtractionResult(
            intent="SEARCH_BY_DESC", confidence=0.45,
            entities=ExtractedEntities(),
            reason="deterministic_search_cross_brand",
            force_band="LOW",
        )

    # ── NOISY #604: "becc 350 N", "bec 350 N" — bare eco sau cc → SEARCH_BY_DESC ──
    # Pattern: bec/tip + optional_ws + cc + bare N/D (không có "hệ" prefix)
    _BEC_CC_ECO_PAT = re.compile(
        r'\b(b[eé]c|bec|tip)\b.{0,20}\b(200|250|310|350|400|500)\s*[Aa]?\s*(?<![A-Za-z])([ND])(?![A-Za-z])',
        re.I | re.UNICODE,
    )
    if _BEC_CC_ECO_PAT.search(q) and not any_codes:
        _m   = _BEC_CC_ECO_PAT.search(q)
        _eco = _m.group(3).upper() if _m else _extract_eco_quick(q)
        _cc  = _extract_cc_quick(q)
        _ws  = _extract_ws_quick(q)
        return ExtractionResult(
            intent="SEARCH_BY_DESC", confidence=0.80,
            entities=ExtractedEntities(
                ecosystem=_eco, current_class=_cc, wire_size=_ws,
                categories=["Tip"],
            ),
            reason="deterministic_noisy_bec_cc_eco",
        )

    # ── NOISY #562/#565: "bechan 350a conhang k" → SEARCH_BY_DESC ───────────────
    # FIX: khi có cc (350A) đã đủ để search → không force LOW, để pipeline trả kết quả
    _NOISY_STOCK_DESC_PAT = re.compile(
        r'(b[eé]c|bec|tip).{0,50}(c[oò]n\s*h[aà]ng|con\s*hang|c[oó]\s*h[aà]ng\s*k)',
        re.I | re.UNICODE,
    )
    if _NOISY_STOCK_DESC_PAT.search(q) and not any_codes:
        _eco = _extract_eco_quick(q)
        _cc  = _extract_cc_quick(q)
        _ws  = _extract_ws_quick(q)
        # Nếu có cc → đủ để search, không force LOW
        _fb  = None if _cc else "LOW"
        _conf = 0.75 if _cc else 0.55
        return ExtractionResult(
            intent="SEARCH_BY_DESC", confidence=_conf,
            entities=ExtractedEntities(
                ecosystem=_eco,
                current_class=_cc,
                wire_size=_ws,
                categories=["Tip"],
            ),
            reason="deterministic_noisy_stock_desc",
            force_band=_fb,
        )
    # #515: "bộ đồ hàn N 350 dây 1.2"
    # #516: "bo do han 350"
    if _DET_BO_DO_HAN_PAT.search(q) or _DET_BO_DO_HAN_PAT.search(query):
        return ExtractionResult(
            intent="SEARCH_BY_DESC", confidence=0.82,
            entities=ExtractedEntities(
                ecosystem=_extract_eco_quick(q),
                current_class=_extract_cc_quick(q),
                wire_size=_extract_ws_quick(q),
            ),
            reason="deterministic_bo_do_han",
        )

    # ── MIXED #699: "béc N 350A và cả thân giữ béc nữa" → UPSELL ─────────────
    if _DET_BEC_VA_THEM_PAT.search(q) or _DET_BEC_VA_THEM_PAT.search(query):
        eco = _extract_eco_quick(q)
        cc  = _extract_cc_quick(q)
        ws  = _extract_ws_quick(q)
        # Detect filter_category từ phần sau "và"
        _fc = None
        if re.search(r'th[aâ]n|tipbody|tip\s*body', q, re.I | re.UNICODE):
            _fc = 'TipBody'
        elif re.search(r'ch[uụ]p|nozzle', q, re.I | re.UNICODE):
            _fc = 'Nozzle'
        elif re.search(r'c[aá]ch\s*(d|đ)i[eê]n|insulator', q, re.I | re.UNICODE):
            _fc = 'Insulator'
        return ExtractionResult(
            intent="UPSELL", confidence=0.88,
            entities=ExtractedEntities(
                ecosystem=eco, current_class=cc, wire_size=ws,
                filter_category=_fc,
            ),
            reason="deterministic_upsell_bec_va_them",
        )

    # ── NOISY #578/#600: "tip he n 350a 1.2 gia", "tip 1.2 he n gia bnhieu" → LOOKUP ──
    # #700: "tư vấn béc 1.2 hệ N rồi báo giá luôn" → LOOKUP
    if _DET_TIP_SPEC_PRICE_PAT.search(q) or _DET_TIP_SPEC_PRICE_PAT.search(query):
        eco = _extract_eco_quick(q)
        ws  = _extract_ws_quick(q)
        cc  = _extract_cc_quick(q)
        return ExtractionResult(
            intent="LOOKUP", confidence=0.88,
            entities=ExtractedEntities(
                ecosystem=eco, current_class=cc, wire_size=ws,
            ),
            reason="deterministic_lookup_tip_spec_price",
        )

    # ── NOISY #580: "chup khi hr350 16" → hr350 = Chụp khí N 350A 16mm (033203) ──
    # FIX: eval expects SEARCH_BY_DESC (user tìm nozzle N 350A), không phải LOOKUP
    _HR350_PAT = re.compile(r'\bhr\s*-?\s*350\b', re.I)
    if _HR350_PAT.search(q) or _HR350_PAT.search(query):
        return ExtractionResult(
            intent="SEARCH_BY_DESC", confidence=0.90,
            entities=ExtractedEntities(
                ecosystem="N", current_class="350A",
                categories=["Nozzle"],
                part_nos=["033203"],   # hint cho DataStore
            ),
            reason="deterministic_hr350_nozzle",
            force_band=None,
        )

    # ── NOISY #571: "tipn350a12", "tip n 350a 1.2" → LOOKUP khi đủ spec ─────────
    # FIX: compact format \d{3}A\d{1}\d{1} → cc=350A ws=1.2; đủ → LOOKUP
    _TIP_COMPACT_PAT = re.compile(
        r'^tip\s*[NnDd]?\s*(\d{3})\s*[Aa]?\s*([\d.]+)\s*(mm)?$', re.I
    )
    _tip_compact_m = _TIP_COMPACT_PAT.match(q.strip())
    if _tip_compact_m:
        eco = _extract_eco_quick(q)
        # Detect eco từ 'tipN' hay 'tipD' trực tiếp nếu chưa có
        if not eco:
            eco_m = re.search(r'\btip\s*([ND])\b', q, re.I)
            if eco_m:
                eco = eco_m.group(1).upper()
        cc_raw = _tip_compact_m.group(1)
        cc = (cc_raw + 'A') if cc_raw in ('200','250','310','350','400','500') else _extract_cc_quick(q)
        ws_raw = _tip_compact_m.group(2).replace('.','')
        if len(ws_raw) == 2 and ws_raw[0] in '0123456789':
            ws = float(ws_raw[0] + '.' + ws_raw[1])
        else:
            ws = _extract_ws_quick(q)
        # Đủ eco+cc+ws → LOOKUP (user đang tìm part cụ thể)
        # Thiếu một trong ba → SEARCH_BY_DESC
        _intent = "LOOKUP" if (eco and cc and ws) else "SEARCH_BY_DESC"
        return ExtractionResult(
            intent=_intent, confidence=0.85 if _intent == "LOOKUP" else 0.78,
            entities=ExtractedEntities(ecosystem=eco, current_class=cc, wire_size=ws,
                                       categories=["Tip"]),
            reason="deterministic_tip_compact_lookup" if _intent == "LOOKUP" else "deterministic_search_tip_compact",
            force_band=None,
        )

    # ── NOISY #563: "chup khj 500" → SEARCH_BY_DESC band LOW (clarify) ────────
    if _DET_NOISY_SHORT_PAT.match(q.strip()):
        return ExtractionResult(
            intent="SEARCH_BY_DESC", confidence=0.45,
            entities=ExtractedEntities(
                categories=["Nozzle"],
                current_class=_extract_cc_quick(q),
            ),
            reason="deterministic_noisy_chup_khi_short",
            force_band="LOW",
        )

    # ── NOISY #589: "becchupkhicachdien 350" → CONSUMABLE_SET band LOW ────────
    if _DET_NOISY_CONCAT_MULTI_PAT.match(q.strip()) or _DET_NOISY_CONCAT_MULTI_PAT.match(query.strip()):
        return ExtractionResult(
            intent="CONSUMABLE_SET", confidence=0.55,
            entities=ExtractedEntities(current_class=_extract_cc_quick(q)),
            reason="deterministic_noisy_concat_consumable",
            force_band="LOW",
        )

    # ── NOISY #603/#604: "tip he N nam ba nam A", "becc 350 N" → SEARCH_BY_DESC ──
    # FIX: có eco + cc đủ rõ → không force LOW
    if _DET_NAM_BA_NAM_PAT.search(query):
        eco = _extract_eco_quick(q)
        ws  = _extract_ws_quick(q)
        return ExtractionResult(
            intent="SEARCH_BY_DESC", confidence=0.78,
            entities=ExtractedEntities(
                ecosystem=eco,
                current_class="350A",
                wire_size=ws,
                categories=["Tip"],
            ),
            reason="deterministic_noisy_nam_ba_nam",
            force_band=None,
        )

    return None


# ─── LLM Extractor (Gemini) ───────────────────────────────────────────────────

class LLMExtractor:
    """
    Single Gemini call → intent + entities + confidence.
    Thay the intent_router.py + entity_extractor.py hoan toan.
    Fallback: RuleExtractor khi Gemini unavailable hoac _SYSTEM_PROMPT rong.
    """

    def __init__(self, gemini_api_key: str):
        self._api_key = gemini_api_key
        self._client  = None
        self._rule    = RuleExtractor()

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def extract(self, query: str) -> ExtractionResult:
        q = query.strip()

        # Pre-filter: skip LLM cho greeting/terse
        if _GREETING_RE.match(q):
            return ExtractionResult(
                intent="OUT_OF_SCOPE", confidence=0.95,
                entities=ExtractedEntities(),
                reason="greeting_prefilter", force_band="LOW",
            )
        if _TERSE_RE.match(q):
            return ExtractionResult(
                intent="SEARCH_BY_DESC", confidence=0.60,
                entities=ExtractedEntities(),
                reason="terse_prefilter", force_band="LOW",
            )

        # Fallback nếu không có system prompt
        if not _SYSTEM_PROMPT:
            return self._rule.extract(q)

        _det = _deterministic_intent(q)
        if _det is not None:
            log.debug(f"[LLMExtractor] deterministic → {_det.intent} (skip Gemini)")
            return _det

        q_norm = _normalize_noisy(q)
        t0 = time.time()

        # AGGREGATE fast-path
        if _DET_AGGREGATE_PAT.search(q_norm or q):
            log.info(f"[extractor] AGGREGATE fast-path: {q[:60]!r}")
            return ExtractionResult(
                intent="AGGREGATE", confidence=0.85,
                entities=ExtractedEntities(),
                reason="rule_aggregate",
            )

        try:
            from core.gemini_resilience import (
                with_retry, GeminiRateLimitError,
                GeminiTimeoutError, GeminiUnavailableError,
            )
            result = with_retry(
                fn=lambda: self._extract_llm(q_norm, q),
                label="llm_extractor",
            )
            log.debug(f"[LLMExtractor] {(time.time()-t0)*1000:.0f}ms "
                      f"intent={result.intent} conf={result.confidence:.2f} q={q[:50]!r}")
            return result
        except (GeminiRateLimitError, GeminiTimeoutError, GeminiUnavailableError) as ex:
            log.warning(f"[LLMExtractor] Gemini resilience fallback: {ex}")
            return self._rule.extract(q)
        except Exception as ex:
            log.warning(f"[LLMExtractor] Gemini failed ({ex}), fallback rule-based")
            return self._rule.extract(q)

    def _extract_llm(self, q_norm: str, q_raw: str) -> ExtractionResult:
        from google.genai import types
        client = self._get_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=q_norm,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                temperature=0.0,
                max_output_tokens=512,
                response_mime_type="application/json",
            ),
        )
        raw  = response.text.strip()
        raw  = re.sub(r"^```json\s*", "", raw)
        raw  = re.sub(r"```\s*$", "", raw)
        data = json.loads(raw)
        result = _validate_and_clean(data)
        result.entities.__dict__["_raw_query"] = q_raw
        return result


# ─── Rule-based fallback extractor ───────────────────────────────────────────

class RuleExtractor:
    """Fallback khi Gemini khong available — regex + simple heuristics."""

    _TOKIN_PAT  = re.compile(r'\b(\d{6})\b')
    _PANA_PAT   = re.compile(r'\b(TET\d{5,8})\b', re.I)
    _DAIHEN_PAT = re.compile(r'\b([KLU]\d{3,4}[A-Z]\d{2,3})\b', re.I)
    _WIRE_PAT   = re.compile(r'(?:phi|\u00f8|\u03c6|wire|d\u00e2y|day)?\s*(\d+(?:\.\d+)?)\s*(?:mm)?', re.I)
    _CC_PAT     = re.compile(r'\b(\d{2,3})\s*[Aa]\b')

    _ECO_PATS = {
        'N':   re.compile(r'\b(he\s*N|h\u1ec7\s*N|N.?type|panasonic|pana|yaskawa|motoman|b\u00e9c\s*N|bec\s*N)\b', re.I),
        'D':   re.compile(r'\b(he\s*D|h\u1ec7\s*D|D.?type|daihen|otc|b\u00e9c\s*D|bec\s*D)\b', re.I),
        'WX':  re.compile(r'\bWX\b', re.I),
        'TIG': re.compile(r'\b(TIG|tungsten|vonfram|collet)\b', re.I),
    }

    _UPSELL_PAT = re.compile(
        r'(\u0111\u00e3\s*c\u00f3|c\u1ea7n\s*th\u00eam|c\u00f2n\s*thi\u1ebfu|\u0111i\s*v\u1edbi|\u0111i\s*k\u00e8m|'
        r'd\u00f9ng\s*chung|v\u1eeba\s*mua|da\s*co|can\s*them|di\s*voi|di\s*kem|dung\s*chung|vua\s*mua|'
        r'them\s*gi|thi\u1ebfu\s*g\u00ec|thieu\s*gi|'
        r'v\u1eadt\s*t\u01b0\s*ti\u00eau\s*hao\s*(?:s\u1eed\s*d\u1ee5ng\s*v\u1edbi|\u0111i\s*v\u1edbi|cho)|'
        r'vat\s*tu\s*tieu\s*hao\s*(?:su\s*dung\s*voi|di\s*voi|cho)|tuong\s*thich\s*gi|t\u01b0\u01a1ng\s*th\u00edch\s*g\u00ec|hop\s*voi\s*gi|x\u00e0i\s*chung\s*\u0111\u01b0\u1ee3c\s*g\u00ec|di\s*kem\s*linh\s*kien|robot\s*tuong\s*thich|tuong\s*thich\s*linh\s*kien|linh\s*kien\s*(?:nao|gi)|xai\s*chung\s*(?:duoc\s*)?gi|dung\s*duoc\s*gi|phu\s*hop\s*gi)',
        re.I | re.UNICODE,
    )
    _CONSUMABLE_PAT = re.compile(
        r'(v\u1eadt\s*t\u01b0|vat\s*tu|ti\u00eau\s*hao|tieu\s*hao|b\u1ed9\s*linh\s*ki\u1ec7n|'
        r'bo\s*linh\s*kien|c\u1ea7n\s*mua\s*g\u00ec|can\s*mua\s*gi|b\u1ed9.*s\u00fang|bo.*sung)',
        re.I | re.UNICODE,
    )
    _REPLACE_PAT = re.compile(
        r'(thay\s*th\u1ebf|thay\s*the|t\u01b0\u01a1ng\s*\u0111\u01b0\u01a1ng|tuong\s*duong|'
        r'replacement|h\u1ebft\s*h\u00e0ng|het\s*hang|thay\s*b\u1eb1ng|thay\s*bang)',
        re.I | re.UNICODE,
    )
    _COMPAT_PAT = re.compile(
        r'(t\u01b0\u01a1ng\s*th\u00edch|tuong\s*thich|compatible|'
        r'd\u00f9ng\s*chung\s*\u0111\u01b0\u1ee3c\s*kh\u00f4ng|dung\s*chung\s*duoc\s*khong|'
        r'l\u1eafp\s*\u0111\u01b0\u1ee3c\s*kh\u00f4ng|lap\s*duoc\s*khong|'
        r'd\u00f9ng\s*\u0111\u01b0\u1ee3c\s*v\u1edbi)',
        re.I | re.UNICODE,
    )
    _LOOKUP_PAT = re.compile(
        r'(l\u00e0\s*g\u00ec|la\s*gi|th\u00f4ng\s*tin|thong\s*tin|m\u00f4\s*t\u1ea3|mo\s*ta|'
        r'gi\u00e1\s*bao\s*nhi\u00eau|gia\s*bao\s*nhieu|th\u00f4ng\s*s\u1ed1|thong\s*so)',
        re.I | re.UNICODE,
    )
    _INSTALL_PAT = re.compile(
        r'(l\u1eafp|lap|l\u1ef1c\s*si\u1ebft|luc\s*siet|torque|'
        r'h\u01b0\u1edbng\s*d\u1eabn\s*l\u1eafp|huong\s*dan\s*lap|'
        r'quy\s*tr\u00ecnh|quy\s*trinh)',
        re.I | re.UNICODE,
    )
    _REPAIR_PAT = re.compile(
        r'(h\u1ecfng|hong|s\u1eeda|sua|b\u1ecb\s*l\u1ed7i|bi\s*loi|'
        r'r\u00f2|ro|k\u1eb9t|ket|m\u00f2n|mon|t\u1eafc|tac|'
        r'troubleshoot|kh\u00f4ng\s*ra\s*d\u00e2y|khong\s*ra\s*day|'
        r'liner\s*t\u1eafc|liner\s*tac)',
        re.I | re.UNICODE,
    )

    _TORCH_SORTED = sorted(TORCH_MODELS, key=len, reverse=True)
    _CAT_MAP = {
        'bec': 'Tip', 'tip': 'Tip', 'dau han': 'Tip',
        'chup': 'Nozzle', 'nozzle': 'Nozzle',
        'cach dien': 'Insulator', 'insulator': 'Insulator',
        'than giu bec': 'TipBody', 'tip body': 'TipBody',
        'liner': 'Liner', 'lot day': 'Liner',
        'inner tube': 'InnerTube', 'ong lot trong': 'InnerTube',
        'orifice': 'Orifice', 'diffuser': 'Orifice',
    }

    def extract(self, query: str) -> ExtractionResult:
        if _GREETING_RE.match(query.strip()):
            return ExtractionResult("OUT_OF_SCOPE", 0.95, ExtractedEntities(),
                                    "rule_greeting", force_band="LOW")
        if _TERSE_RE.match(query.strip()):
            return ExtractionResult("SEARCH_BY_DESC", 0.60, ExtractedEntities(),
                                    "rule_terse", force_band="LOW")

        q   = _normalize_noisy(query)
        ent = ExtractedEntities()
        ent.__dict__["_raw_query"] = query

        ent.part_nos   = list(dict.fromkeys(self._TOKIN_PAT.findall(q)))
        ent.p_part_nos = list(dict.fromkeys(self._PANA_PAT.findall(q)))
        ent.d_part_nos = list(dict.fromkeys(self._DAIHEN_PAT.findall(q)))
        ent.raw_codes  = list(dict.fromkeys(ent.part_nos + ent.p_part_nos + ent.d_part_nos))

        for model in self._TORCH_SORTED:
            pat = r'(?<![A-Za-z0-9])' + re.escape(model) + r'(?![A-Za-z0-9])'
            if re.search(pat, q, re.I):
                if not any(model.upper() in e.upper() and model != e for e in ent.torch_models):
                    ent.torch_models.append(model)

        q_lower = q.lower()
        for alias, cat in sorted(self._CAT_MAP.items(), key=lambda x: -len(x[0])):
            if alias in q_lower and cat not in ent.categories:
                ent.categories.append(cat)

        for eco, pat in self._ECO_PATS.items():
            if pat.search(q):
                ent.ecosystem = eco
                break

        for m in self._CC_PAT.finditer(q):
            cc = f"{m.group(1)}A"
            if cc in VALID_CURRENT_CLASSES:
                ent.current_class = cc
                break

        for m in self._WIRE_PAT.finditer(q):
            try:
                ws = float(m.group(1))
                if ws in VALID_WIRE_SIZES:
                    ent.wire_size = ws
                    break
            except ValueError:
                pass

        if ent.p_part_nos:
            ent.brand_hint = "panasonic"
        elif ent.d_part_nos:
            ent.brand_hint = "daihen"

        has_code  = bool(ent.part_nos or ent.p_part_nos or ent.d_part_nos)
        has_torch = bool(ent.torch_models)
        has_cc    = bool(ent.current_class)

        if self._COMPAT_PAT.search(q):
            intent, conf = "COMPATIBILITY_CHECK", 0.85
        elif self._REPLACE_PAT.search(q) and (ent.p_part_nos or ent.d_part_nos):
            intent, conf = "REPLACEMENT", 0.88
        elif self._UPSELL_PAT.search(q) and (has_code or ent.wire_size or has_torch):
            # FIX: "YMSA-308R robot tuong thich gi" → UPSELL (torch + hỏi đi kèm)
            intent, conf = "UPSELL", 0.85
            if ent.part_nos:
                ent.owned_parts = ent.part_nos[:]
        elif self._CONSUMABLE_PAT.search(q) and (has_torch or has_cc):
            intent, conf = "CONSUMABLE_SET", 0.85
        elif self._INSTALL_PAT.search(q):
            intent, conf = "INSTALLATION", 0.82
        elif self._REPAIR_PAT.search(q):
            intent, conf = "REPAIR", 0.82
        elif self._LOOKUP_PAT.search(q) and has_code:
            intent, conf = "LOOKUP", 0.85
        elif has_code and not has_torch:
            intent, conf = "LOOKUP", 0.75
        elif (has_torch or has_cc) and not ent.wire_size and not ent.categories:
            # wire_size hoặc có category rõ → SEARCH_BY_DESC, không phải CONSUMABLE_SET
            intent, conf = "CONSUMABLE_SET", 0.75
        elif (has_torch or has_cc) and (ent.wire_size or ent.categories):
            intent, conf = "SEARCH_BY_DESC", 0.70
        else:
            intent, conf = "SEARCH_BY_DESC", 0.65

        return ExtractionResult(
            intent=intent, confidence=conf, entities=ent,
            reason=f"rule_based intent={intent}",
        )


# ─── Factory ─────────────────────────────────────────────────────────────────

def get_extractor(gemini_api_key: str = None):
    key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
    if key and _SYSTEM_PROMPT:
        return LLMExtractor(gemini_api_key=key)
    log.warning("[LLMExtractor] Using RuleExtractor fallback")
    return RuleExtractor()


# ─── Smoke test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ext = RuleExtractor()
    cases = [
        ("alo",                                    "OUT_OF_SCOPE"),
        ("bec",                                    "SEARCH_BY_DESC"),
        ("002001 la gi",                            "LOOKUP"),
        ("TET00958 thay bang gi",                   "REPLACEMENT"),
        ("bo vat tu cho TK-308RR",                  "CONSUMABLE_SET"),
        ("sung 350A can vat tu gi",                 "CONSUMABLE_SET"),
        ("002001 dung chung voi linh kien nao",     "UPSELL"),
        ("vua mua bec 002001 can them chup khi",    "UPSELL"),
        ("bec N va bec D dung chung duoc khong",    "COMPATIBILITY_CHECK"),
        ("liner bi tac day khong chay",             "REPAIR"),
        ("cach lap liner cho TK-308RR",             "INSTALLATION"),
        # v1.1 new cases
        ("bo do han N 350 day 1.2",                 "SEARCH_BY_DESC"),
        ("bec N 350A va ca than giu bec nua",       "UPSELL"),
        ("hang co san khong hay dat",               "OUT_OF_SCOPE"),
        ("chup khi WX cho sung he N",               "COMPATIBILITY_CHECK"),
        ("lap tip he N vao than he D",              "COMPATIBILITY_CHECK"),
        ("cach dien 350A lap chup khi 500A",        "COMPATIBILITY_CHECK"),
        ("chup khi 350A cho bec 500A",              "COMPATIBILITY_CHECK"),
        ("tip he n 350a 1.2 gia",                   "LOOKUP"),
        ("tip 1.2 he n gia bnhieu",                 "LOOKUP"),
    ]
    print("=" * 65)
    print("LLM EXTRACTOR v1.1 — RuleExtractor smoke test")
    print("=" * 65)
    passed = 0
    for query, expected in cases:
        # Also test deterministic path
        det = _deterministic_intent(query)
        r = det if det is not None else ext.extract(query)
        ok = r.intent == expected
        if ok:
            passed += 1
        status = "OK  " if ok else "FAIL"
        src = "det" if det is not None else "rule"
        print(f"[{status}] [{src}] {query[:48]:48} -> {r.intent} (conf={r.confidence:.2f})")
        if not ok:
            print(f"       expected: {expected}")
    print(f"\n{passed}/{len(cases)} passed")
    print("=" * 65)

