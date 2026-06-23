# core/fuzzy_corrector.py
# TOKINARC FuzzyCorrector — Tier 1 Retrieval Layer
# =================================================
# Sửa typo, recover token boundary, map alias VN trước khi đưa vào exact match.
#
# Pipeline position:
#   raw query → alias_normalizer → numeric_tokenizer → FUZZY_CORRECTOR → exact_match_engine
#                                                            ↑ đây
#
# Bài toán cụ thể eval_700 miss (193/200):
#   - TK308RR / TK308-RR / TK 308RR → cần thành "TK-308RR"
#   - tipN350a12 / tip N350 1.2 → "tip N 350A 1.2mm"
#   - "đầu hàn N 350" / "dau han N 350" → category=Tip + ecosystem=N
#   - "TK309R" mất ký tự cuối → suggest "TK-309R1" (Levenshtein=1)
#   - "MAG350" / "MAG 350" / "mag-350" → MAG-350 (canonical Panasonic)
#   - typo phonetic: "túng hàn" → "súng hàn", "bíc" → "béc"
#
# Output: FuzzyResult với corrections list + confidence + variants candidates.
# Downstream (exact_match_engine) thử từng variant trước khi fallback search.
#
# Dependencies: stdlib only (difflib, re, unicodedata) — không cần rapidfuzz/Levenshtein.
#
# UTF-8 NO BOM

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("tokinarc.fuzzy_corrector")


# ══════════════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════════════

# Ngưỡng similarity cho fuzzy match (0..1)
PART_NO_SIM_THRESHOLD       = 0.80   # part code: TK-308RR — typo 1-2 ký tự OK
MODEL_CODE_SIM_THRESHOLD    = 0.82   # torch model: MAG-350W — typo 1-2 ký tự
TOKEN_SIM_THRESHOLD         = 0.85   # word level VN: cần chặt hơn (tránh false positive)
MIN_CODE_LEN_FOR_FUZZY      = 4      # < 4 ký tự không fuzzy (quá nhiều false positive)
MAX_CANDIDATES_PER_TYPE     = 3      # cap candidate cho từng loại (part_no / model_code / category)

# Phonetic VN — typo phổ biến do nghe sai / gõ vội
# QUAN TRỌNG: chỉ fix các typo THỰC SỰ là typo (không phải synonym).
# Synonym như "đầu hàn" / "cúp khí" → giữ nguyên, để alias dict infer category.
_VN_PHONETIC_FIX = {
    # nasal / vowel typo trong "súng hàn"
    "túng":  "súng",     # túng hàn → súng hàn
    "tủng":  "súng",
    # béc typo
    "bíc":   "béc",
    "bich":  "béc",
    "bach":  "béc",      # rare typo
    "bék":   "béc",
}

# VN alias → canonical category (lower-case keys, normalized không dấu)
# Sync với CategoryVocabulary trong tokinarc_schema_v12.py line 444-490
_CATEGORY_ALIASES: Dict[str, str] = {
    # Tip — đầu/mũi/béc hàn / đầu tiếp điện
    "bec nhom": "Tip", "bec han nhom": "Tip", "tip nhom": "Tip",
    "nhom": "Tip", "nhôm": "Tip", "aluminum tip": "Tip", "mig nhom": "Tip",
    "bec mig": "Tip", "bec mag": "Tip", "bec co2": "Tip",
    "tip": "Tip", "bec": "Tip", "bec han": "Tip", "dau han": "Tip", "mui han": "Tip",
    "contact tip": "Tip", "vonfram": "TungstenElectrode", "dien cuc vonfram": "TungstenElectrode", "dien cuc tungsten": "TungstenElectrode", "dau hand": "Tip", "duau han": "Tip",
    "dau tiep dien": "Tip", "tiep dien": "Tip",
    # Nozzle — chụp/cúp khí
    "nozzle": "Nozzle", "chup khi": "Nozzle", "cup khi": "Nozzle", "chup": "Nozzle",
    "gas cup": "Nozzle", "gas nozzle": "Nozzle", "cup": "Nozzle",
    # Insulator — cách điện / vỏ cách điện
    "insulator": "Insulator", "cach dien": "Insulator", "boc cach dien": "Insulator",
    "vo cach dien": "Insulator",
    # Orifice — chia khí / khuếch tán / diffuser
    "orifice": "Orifice", "chia khi": "Orifice", "su chia khi": "Orifice",
    "diffuser": "Orifice", "difuser": "Orifice",
    "su khuech tan": "Orifice", "khuech tan": "Orifice",
    # TipBody — thân giữ béc / đầu giữ béc
    "tip body": "TipBody", "tipbody": "TipBody", "than giu bec": "TipBody",
    "than giu": "TipBody", "holder": "TipBody", "giu bec": "TipBody",
    "dau giu bec": "TipBody", "than bec": "TipBody",
    # InnerTube — ống lót trong (PRIORITY before Liner: "ong lot trong" cụ thể hơn "ong lot")
    "ong lot trong": "InnerTube", "inner tube": "InnerTube", "innertube": "InnerTube",
    "ong trong": "InnerTube", "ruot ong": "InnerTube", "inner liner": "InnerTube",
    "ong long trong": "InnerTube",
    # Liner — ống lót / ruột cáp
    "liner": "Liner", "ong lot": "Liner", "lot day": "Liner",
    "conduit liner": "Liner", "ruot cap": "Liner",
    # TungstenElectrode — expanded aliases
    "tungsten": "TungstenElectrode", "vonfram": "TungstenElectrode",
    "electrode": "TungstenElectrode", "dien cuc": "TungstenElectrode",
    "dien cuc tungsten": "TungstenElectrode", "dien cuc vonfram": "TungstenElectrode",
    "tungsten electrode": "TungstenElectrode", "tungstenelectrode": "TungstenElectrode",
    "wolframelectrode": "TungstenElectrode", "wolfram": "TungstenElectrode",
    # BackCap — nắp đuôi TIG
    "back cap": "BackCap", "backcap": "BackCap", "nap dau": "BackCap",
    "nap hau": "BackCap", "nap duoi": "BackCap", "chup duoi": "BackCap",
    "nap lung": "BackCap", "nap phia duoi": "BackCap",
    "wave washer": "WaveWasher", "vong dem lo xo": "WaveWasher",
    "vong dem": "WaveWasher", "lo xo dem": "WaveWasher",
    # TipAdapter
    "tip adapter": "TipAdapter", "dau noi bec": "TipAdapter",
    "dau adapter": "TipAdapter",
    # LinerORing
    "o ring liner": "LinerORing", "oring liner": "LinerORing",
    "liner o-ring": "LinerORing", "vong o liner": "LinerORing",
    # TorchBody
    "torch body": "TorchBody", "than sung": "TorchBody", "cum than": "TorchBody",
    # WXCenterCeramic
    "wx center ceramic": "WXCenterCeramic", "center ceramic": "WXCenterCeramic",
    "su dinh tam": "WXCenterCeramic", "dinh tam": "WXCenterCeramic",
    # Collet — kẹp điện cực TIG (holder for tungsten electrode)
    "collet": "Collet", "kep cuc": "Collet",
    "than kep dien cuc": "ColletBody",
    # "kẹp điện cực" alone without "thân" → TungstenElectrode (người dùng hỏi electrode)
    "kep dien cuc": "TungstenElectrode", "kep dien": "TungstenElectrode",
    "dien cuc kep": "TungstenElectrode",
    # ColletBody — thân kẹp
    "collet body": "ColletBody", "than collet": "ColletBody",
    "than kep": "ColletBody", "colletbody": "ColletBody",
    # CeramicNozzle — chụp sứ (TIG)
    "ceramic nozzle": "CeramicNozzle", "ceramicnozzle": "CeramicNozzle",
    "chup su": "CeramicNozzle", "chup gom": "CeramicNozzle", "cup gom": "CeramicNozzle",
    "cup su": "CeramicNozzle",
    # PowerCable — cáp điện / cáp nguồn
    "power cable": "PowerCable", "cap dien": "PowerCable",
    "cap nguon": "PowerCable", "powercable": "PowerCable",
    # GasHose — ống gas / ống khí
    "gas hose": "GasHose", "ong gas": "GasHose", "ong khi": "GasHose",
    "gashose": "GasHose",
    # Handle — tay cầm
    "handle": "Handle", "tay cam": "Handle", "can sung": "Handle",
    # InsulationCollar — vòng cách điện / vòng cách
    "insulation collar": "InsulationCollar", "insulationcollar": "InsulationCollar",
    "vong cach dien": "InsulationCollar", "vong cach": "InsulationCollar",
    # WXNozzleSleeve
    "wx nozzle sleeve": "WXNozzleSleeve", "nozzle sleeve": "WXNozzleSleeve",
    "wxnozzlesleeve": "WXNozzleSleeve",
    # WXCoverRubber
    "wx cover rubber": "WXCoverRubber", "cover rubber": "WXCoverRubber",
    "wxcoverrubber": "WXCoverRubber",
    # InsulationSpacer
    "insulation spacer": "InsulationSpacer", "insulationspacer": "InsulationSpacer",
    "vong cach lo": "InsulationSpacer",
}

# Ecosystem aliases — ngắn gọn user hay dùng
_ECOSYSTEM_ALIASES: Dict[str, str] = {
    "n":           "N",   "he n":     "N",  "hen":      "N",
    "d":           "D",   "he d":     "D",  "daihen":   "D",
    "wx":          "WX",  "he wx":    "WX", "wexx":     "WX",
    "tig":         "TIG", "he tig":   "TIG",
    "tcc":         "TCC", "he tcc":   "TCC",
    "panasonic":   "N",   "panaso":   "N",  "pana":     "N",
    "otc":         "O",   "o brand":  "O",
    "tcc-350r":    "TCC", "tcc350r":  "TCC", "tcc 350":  "TCC",
}

# Robot model aliases — cách user gọi robot Yaskawa/Motoman (normalized không dấu, lowercase)
# Fallback cứng; runtime ưu tiên ds.meta["robot_aliases"] (v20). Map -> canonical robot model.
_ROBOT_ALIASES: Dict[str, str] = {
    "ma1440": "MA1440", "ar1440": "MA1440", "1.4m": "MA1440", "1,4m": "MA1440",
    "1.4 met": "MA1440", "1.4met": "MA1440", "1440": "MA1440",
    "ma2010": "MA2010", "ar2010": "MA2010", "2.0m": "MA2010", "2,0m": "MA2010",
    "2.0 met": "MA2010", "2010": "MA2010",
    "ar1730": "AR1730", "mh24": "AR1730", "1.7m": "AR1730", "1,7m": "AR1730", "1730": "AR1730",
    "ar700": "AR700", "ar900": "AR900", "ar1440e": "AR1440E", "1440e": "AR1440E",
}


# Current class aliases — "350A", "350 A", "350a", "tre tram nam muoi"
_CURRENT_CLASS_PATTERNS = [
    (r'\b(\d{2,3})\s*[aA]\b',  lambda m: f"{m.group(1)}A"),
    (r'\b(\d{2,3})amp(?:e|ere|er)?s?\b', lambda m: f"{m.group(1)}A"),
]


# ══════════════════════════════════════════════════════════════════════════════
# Result dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FuzzyCorrection:
    """Một bước correction — original → corrected với confidence."""
    original:   str
    corrected:  str
    kind:       str   # "part_no" | "model_code" | "vn_alias" | "phonetic" | "boundary" | "ecosystem" | "current_class"
    confidence: float = 1.0   # 0..1


@dataclass
class FuzzyResult:
    """
    Output của FuzzyCorrector.correct().

    Attributes:
        original_query:  query đầu vào
        corrected_query: query sau correction
        corrections:     list các bước correction áp dụng
        part_no_candidates:    list canonical part_no đề xuất (max 3)
        model_code_candidates: list canonical model_code đề xuất (max 3)
        category_hints:        list PartCategory inferred từ alias (vd ["Tip"])
        ecosystem_hint:        Optional[str] — N/D/WX/TIG/TCC
        current_class_hint:    Optional[str] — "350A"
        wire_size_hint:        Optional[float] — 1.2
        robot_model_hint:      Optional[str] — robot model resolve từ alias (MA1440)
        confidence:      overall confidence (0..1) — min của các correction
    """
    original_query:        str
    corrected_query:       str
    corrections:           List[FuzzyCorrection] = field(default_factory=list)
    part_no_candidates:    List[Tuple[str, float]] = field(default_factory=list)  # (part_no, sim)
    model_code_candidates: List[Tuple[str, float]] = field(default_factory=list)
    category_hints:        List[str] = field(default_factory=list)
    ecosystem_hint:        Optional[str] = None
    current_class_hint:    Optional[str] = None
    wire_size_hint:        Optional[float] = None
    robot_model_hint:      Optional[str] = None
    confidence:            float = 1.0

    def has_correction(self) -> bool:
        return bool(self.corrections) or self.corrected_query != self.original_query

    def to_dict(self) -> dict:
        return {
            "original":             self.original_query,
            "corrected":            self.corrected_query,
            "corrections":          [
                {"original": c.original, "corrected": c.corrected,
                 "kind": c.kind, "confidence": c.confidence}
                for c in self.corrections
            ],
            "part_no_candidates":    self.part_no_candidates[:3],
            "model_code_candidates": self.model_code_candidates[:3],
            "category_hints":        self.category_hints,
            "ecosystem_hint":        self.ecosystem_hint,
            "current_class_hint":    self.current_class_hint,
            "wire_size_hint":        self.wire_size_hint,
            "robot_model_hint":      self.robot_model_hint,
            "confidence":            self.confidence,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _strip_accents(s: str) -> str:
    """Bỏ dấu tiếng Việt — phục vụ phonetic match."""
    nfkd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).replace("đ", "d").replace("Đ", "D")


def _normalize_for_compare(s: str) -> str:
    """Normalize aggressive cho fuzzy compare: lower + strip accent + remove non-alnum."""
    s = _strip_accents(s.lower())
    return re.sub(r"[^a-z0-9]", "", s)


def _similarity(a: str, b: str) -> float:
    """Ratio 0..1 từ difflib SequenceMatcher (Levenshtein-like)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _is_code_like(token: str) -> bool:
    """Token trông giống part code: chứa cả chữ + số, dài ≥ 3."""
    if len(token) < 3:
        return False
    has_alpha = any(c.isalpha() for c in token)
    has_digit = any(c.isdigit() for c in token)
    return has_alpha and has_digit


# ══════════════════════════════════════════════════════════════════════════════
# FuzzyCorrector main class
# ══════════════════════════════════════════════════════════════════════════════

class FuzzyCorrector:
    """
    Tier 1 fuzzy correction layer.

    Usage:
        corrector = FuzzyCorrector(ds=data_store)
        result = corrector.correct("tipn350a12 he N")
        # → corrected="tip N 350A 1.2mm he N"
        # → part_no_candidates=[]
        # → category_hints=["Tip"], ecosystem_hint="N",
        #   current_class_hint="350A", wire_size_hint=1.2

    Strategy (apply theo thứ tự):
        1. Token boundary recovery (tipN350a12 → tip n 350 a 12)
        2. Phonetic VN fix (túng hàn → súng hàn, bíc → béc)
        3. Numeric pattern fix (350a → 350A, 12 → 1.2mm context)
        4. Alias → category/ecosystem/current_class inference
        5. Fuzzy match part_no & model_code candidates
    """

    def __init__(self, ds=None):
        """
        Args:
            ds: TokinarcDataStore instance (optional — lazy load).
                Dùng để build part_no_index & model_code_index cho fuzzy lookup.
        """
        self._ds = ds
        self._part_no_index:    List[str] = []
        self._model_code_index: List[str] = []
        # All known codes incl aliases (Panasonic/Daihen/OTC) for cross-brand resolve
        self._all_part_codes:   Set[str] = set()
        self._all_model_codes:  Set[str] = set()
        self._indexes_built = False

    # ── Lazy DataStore ──────────────────────────────────────────────────────────

    @property
    def ds(self):
        if self._ds is None:
            from data_store import get_data_store
            self._ds = get_data_store()
        return self._ds

    def _ensure_indexes(self):
        """Build part_no & model_code list 1 lần. Idempotent. Resilient với DataStore fail."""
        if self._indexes_built:
            return
        try:
            ds = self.ds
        except Exception as e:
            log.warning(f"[FuzzyCorrector] DataStore load failed: {e} — fuzzy code match disabled")
            self._indexes_built = True
            return
        if ds is None:
            log.warning("[FuzzyCorrector] DataStore unavailable, fuzzy code match disabled")
            self._indexes_built = True
            return

        # Part codes — canonical tokin_part_no + cross-brand aliases
        for pno, part in ds.parts.items():
            self._part_no_index.append(pno)
            self._all_part_codes.add(pno)
            for alias_field in ("p_part_nos", "d_part_nos", "o_part_nos"):
                for alias in (part.get(alias_field) or []):
                    if alias:
                        self._all_part_codes.add(alias)

        # Model codes — canonical model_code + cross-brand model aliases
        for mc, torch in ds.torches.items():
            self._model_code_index.append(mc)
            self._all_model_codes.add(mc)
            for alias_field in ("p_model_codes", "d_model_codes", "o_model_codes"):
                for alias in (torch.get(alias_field) or []):
                    if alias:
                        self._all_model_codes.add(alias)

        self._indexes_built = True
        log.info(f"[FuzzyCorrector] indexes built: "
                 f"{len(self._part_no_index)} part_nos (+{len(self._all_part_codes) - len(self._part_no_index)} aliases), "
                 f"{len(self._model_code_index)} model_codes (+{len(self._all_model_codes) - len(self._model_code_index)} aliases)")

    # ── Public API ──────────────────────────────────────────────────────────────

    def correct(self, query: str) -> FuzzyResult:
        """
        Apply toàn bộ pipeline correction lên query.

        Returns:
            FuzzyResult với corrected query + structured hints + fuzzy candidates.
        """
        self._ensure_indexes()
        result = FuzzyResult(original_query=query, corrected_query=query)

        if not query or not query.strip():
            return result

        # Step 1: token boundary recovery
        q1 = self._recover_boundary(query, result)

        # Step 2: phonetic VN fix
        q2 = self._fix_phonetic(q1, result)

        # Step 3: numeric pattern normalize
        q3 = self._normalize_numeric(q2, result)

        # Step 4: alias inference (category, ecosystem, current_class, wire_size)
        self._infer_hints(q3, result)

        # Step 5: fuzzy code candidates
        self._suggest_code_candidates(q3, result)

        result.corrected_query = q3
        # Overall confidence = min of correction confidences (or 1.0 if no correction)
        if result.corrections:
            result.confidence = min(c.confidence for c in result.corrections)

        return result

    # ── Step 1: Token boundary recovery ─────────────────────────────────────────

    def _recover_boundary(self, query: str, result: FuzzyResult) -> str:
        r"""
        Fix glued tokens: tipn350a12 → tip n 350 a 12

        Patterns (apply theo thứ tự, không overlap):
        - tip|nozzle|bec|chup + (n|d|wx) + (\d{2,3}) + a?(\d+)?  → split
        - prefix CODE + suffix digits/letters (TK308RR → TK-308RR)
        """
        original = query
        q = query

        # Pattern 1: glued category + ecosystem + current_class + wire
        # e.g. "tipn350a12", "becn350a12", "chupn500", "nozzlen350a"
        cat_kw = r"(tip|bec|nozzle|chup|orifice|liner|insulator)"
        glued_full = re.compile(
            rf"\b{cat_kw}([nNdD]|wx|WX|tig|TIG|tcc|TCC)(\d{{2,3}})[aA]?(\d{{1,2}})?\b",
            re.IGNORECASE,
        )
        def _split_glued(m):
            cat, eco, amp, wire = m.group(1), m.group(2), m.group(3), m.group(4)
            parts_out = [cat.lower(), eco.upper(), f"{amp}A"]
            if wire:
                # 12 → 1.2; 09 → 0.9; 16 → 1.6
                if len(wire) == 2:
                    parts_out.append(f"{wire[0]}.{wire[1]}mm")
                else:
                    parts_out.append(f"{wire}mm")
            return " ".join(parts_out)
        q_new = glued_full.sub(_split_glued, q)
        if q_new != q:
            result.corrections.append(FuzzyCorrection(
                original=q, corrected=q_new, kind="boundary", confidence=0.95))
            q = q_new

        # Pattern 2: part code missing hyphen — TK308RR → TK-308RR, MAG350 → MAG-350
        # Chỉ áp dụng cho prefix viết hoa 2-4 ký tự + ≥3 digit
        _ROBOT_PREFIXES = {"MA", "AR", "MH", "EA", "HP"}  # Yaskawa/Motoman robot series
        known_prefixes = {"TK", "MAG", "MIG", "TIG", "TL", "TC", "TCC", "ACC", "ACT",
                          "TS", "YMS", "YMSA", "YMENS", "SRCT", "DSRC", "WX", "TA",
                          "FX", "FXS", "CSL", "CSH", "CSA", "TLA", "CSHA"}
        code_no_hyphen = re.compile(r"\b([A-Z]{2,4})(\d{2,4}[A-Z0-9]{0,3})\b")
        def _add_hyphen(m):
            prefix, suffix = m.group(1), m.group(2)
            # Robot model prefix -> KHONG chen gach (MA1440 giu nguyen)
            if prefix in _ROBOT_PREFIXES:
                return m.group(0)
            return f"{prefix}-{suffix}"
        q_new = code_no_hyphen.sub(_add_hyphen, q)
        if q_new != q:
            # Confidence cao chi voi prefix biet truoc (TK, MAG, MIG, TL, ...)
            # Re-check neu prefix la known part/torch prefix
            for m in code_no_hyphen.finditer(query):
                if m.group(1) in _ROBOT_PREFIXES:
                    continue  # robot model -- bo qua
                if m.group(1) in known_prefixes:
                    result.corrections.append(FuzzyCorrection(
                        original=m.group(0), corrected=f"{m.group(1)}-{m.group(2)}",
                        kind="boundary", confidence=0.95))
                    break
            else:
                # Unknown prefix — vẫn áp dụng nhưng confidence thấp hơn
                result.corrections.append(FuzzyCorrection(
                    original=q, corrected=q_new, kind="boundary", confidence=0.75))
            q = q_new

        # Pattern 3: "tip n350a 1.2" (space giữa eco và amp bị mất)
        q_new = re.sub(
            r"\b([nNdD]|wx|WX|tig|TIG|tcc|TCC)(\d{2,3})[aA]\b",
            lambda m: f"{m.group(1).upper()} {m.group(2)}A",
            q,
        )
        if q_new != q:
            result.corrections.append(FuzzyCorrection(
                original=q, corrected=q_new, kind="boundary", confidence=0.9))
            q = q_new

        # Pattern 4: "TK 308RR" / "MAG 350" / "tk 309r1" — known prefix + space + digit suffix → hyphenate
        # Chỉ áp dụng cho prefix biết trước để tránh false positive. Canonicalize UPPER.
        known_prefixes_re = r"(?:TK|MAG|MIG|TIG|TL|TC|TCC|ACC|ACT|TS|YMS|YMSA|YMENS|HR)"
        q_new = re.sub(
            rf"\b({known_prefixes_re})\s+(\d{{2,4}}[a-zA-Z0-9]{{0,3}})\b",
            lambda m: f"{m.group(1).upper()}-{m.group(2).upper()}",
            q,
            flags=re.IGNORECASE,
        )
        if q_new != q:
            result.corrections.append(FuzzyCorrection(
                original=q, corrected=q_new, kind="boundary", confidence=0.9))
            q = q_new

        if q != original:
            log.debug(f"[FuzzyCorrector] boundary: '{original}' → '{q}'")
        return q

    # ── Step 2: Phonetic VN fix ─────────────────────────────────────────────────

    def _fix_phonetic(self, query: str, result: FuzzyResult) -> str:
        """Sửa typo phonetic VN phổ biến (túng → súng, bíc → béc...)."""
        original = query
        q = query
        ql = q.lower()

        for typo, correct in _VN_PHONETIC_FIX.items():
            # Sửa context-aware: chỉ replace nếu là token độc lập
            pat = re.compile(rf"\b{re.escape(typo)}\b", re.IGNORECASE)
            if pat.search(ql):
                # Soft replace — giữ case của ký tự đầu
                new_q = pat.sub(correct, q)
                if new_q != q:
                    result.corrections.append(FuzzyCorrection(
                        original=typo, corrected=correct, kind="phonetic", confidence=0.85))
                    q = new_q
                    ql = q.lower()

        if q != original:
            log.debug(f"[FuzzyCorrector] phonetic: '{original}' → '{q}'")
        return q

    # ── Step 3: Numeric normalize ───────────────────────────────────────────────

    def _normalize_numeric(self, query: str, result: FuzzyResult) -> str:
        """Normalize current_class (350a → 350A), wire size, amp suffix."""
        q = query

        # "350 a" / "350a" / "350 A" → "350A"
        q_new = re.sub(r"\b(\d{2,3})\s*[aA]\b(?!\.)", lambda m: f"{m.group(1)}A", q)
        if q_new != q:
            result.corrections.append(FuzzyCorrection(
                original=q, corrected=q_new, kind="current_class", confidence=1.0))
            q = q_new

        # FIX: "X ly" / "X.Y ly" → wire size mm notation
        # "1.6 ly" / "1.6ly" → "1.6mm"
        # "0.9 ly" / "0.9ly" → "0.9mm"
        # "1 ly" alone (without suffix digit) → "1.0mm"
        # "2.0 ly" → "2.0mm"
        def _ly_to_mm(m):
            int_part = m.group(1)
            dec_part = m.group(2)
            if dec_part:
                return f"{int_part}.{dec_part}mm"
            else:
                return f"{int_part}.0mm"
        q_new = re.sub(
            r"\b(\d)(?:\.(\d))?\s*ly\b(?!\s*\d)",
            _ly_to_mm,
            q,
            flags=re.IGNORECASE,
        )
        if q_new != q:
            result.corrections.append(FuzzyCorrection(
                original=q, corrected=q_new, kind="wire_size", confidence=0.95))
            q = q_new

        # "1.2 mm" → "1.2mm" (gắn liền)
        q = re.sub(r"\b(\d\.\d)\s*mm\b", lambda m: f"{m.group(1)}mm", q)

        # Wire size implicit sau current_class — heuristic: "350A 12" / "350A 09" → "350A 1.2mm"
        # Match: số 2 digit theo sau current_class, KHÔNG có suffix mm/m/cm.
        q_new = re.sub(
            r"\b(\d{3}A)\s+(\d{2})\b(?!\s*\.?\s*(?:mm|m|cm))",
            lambda m: f"{m.group(1)} {m.group(2)[0]}.{m.group(2)[1]}mm",
            q,
        )
        if q_new != q:
            result.corrections.append(FuzzyCorrection(
                original=q, corrected=q_new, kind="wire_size", confidence=0.85))
            q = q_new

        # Form đã có dấu chấm nhưng không có suffix: "350A 1.2" → "350A 1.2mm"
        q_new = re.sub(
            r"\b(\d{3}A)\s+(\d\.\d)\b(?!\s*mm)",
            lambda m: f"{m.group(1)} {m.group(2)}mm",
            q,
        )
        if q_new != q:
            result.corrections.append(FuzzyCorrection(
                original=q, corrected=q_new, kind="wire_size", confidence=0.95))
            q = q_new

        return q

    # ── Step 4: Alias → hints inference ─────────────────────────────────────────

    def _infer_hints(self, query: str, result: FuzzyResult) -> None:
        """
        Extract structured hints từ query đã normalize.
        Không thay đổi query — chỉ populate result fields.
        """
        q_norm = _strip_accents(query.lower())

        # Category hints — longest-alias-wins + shadow removal
        # Bug-fix: "tipbody" contains "tip" → cả 2 alias match.
        # Pick the alias with longest substring, then remove its span so other
        # shorter aliases don't shadow it.
        # Sort by alias length desc, iterate; mark consumed positions.
        consumed = [False] * len(q_norm)
        ordered_aliases = sorted(_CATEGORY_ALIASES.items(), key=lambda kv: -len(kv[0]))
        for alias, cat in ordered_aliases:
            start = 0
            while True:
                idx = q_norm.find(alias, start)
                if idx < 0:
                    break
                # Skip if any char in this span already consumed (shadowed)
                if any(consumed[idx:idx + len(alias)]):
                    start = idx + 1
                    continue
                # Mark consumed
                for i in range(idx, idx + len(alias)):
                    consumed[i] = True
                if cat not in result.category_hints:
                    result.category_hints.append(cat)
                start = idx + len(alias)

        # Ecosystem hint — first match wins
        if result.ecosystem_hint is None:
            for alias, eco in _ECOSYSTEM_ALIASES.items():
                # Multi-word alias: cần boundary
                if " " in alias:
                    pat = re.compile(rf"\b{re.escape(alias)}\b")
                else:
                    pat = re.compile(rf"\b{re.escape(alias)}\b")
                if pat.search(q_norm):
                    result.ecosystem_hint = eco
                    break

        # Standalone "n" / "d" — chỉ valid nếu có context (theo sau current_class hoặc "he")
        if result.ecosystem_hint is None:
            m = re.search(r"\b(?:he\s+)?([ndo])\b\s*(?:\d{2,3}a|sung|han|bec)", q_norm)
            if m:
                eco = m.group(1).upper()
                if eco == "O":
                    eco = "O"
                result.ecosystem_hint = eco

        # Current class — pattern "350A"
        m = re.search(r"\b(\d{2,3})A\b", query)
        if m:
            result.current_class_hint = f"{m.group(1)}A"

        # Wire size — pattern "1.2mm" / "1.2 mm" / "0.9mm"
        m = re.search(r"\b(\d\.\d)\s*mm\b", query)
        if m:
            try:
                result.wire_size_hint = float(m.group(1))
            except ValueError:
                pass

        # Robot model hint — resolve alias "1,4 mét"/"1.4m"/"1440" -> MA1440.
        # Ưu tiên alias từ ds.meta (data v20), fallback _ROBOT_ALIASES cứng.
        if result.robot_model_hint is None:
            alias_map = dict(_ROBOT_ALIASES)
            try:
                ds = self.ds
                meta_aliases = getattr(ds, "robot_aliases", None) if ds else None
                if meta_aliases:
                    alias_map.update(meta_aliases)
            except Exception:
                pass
            # Chuẩn hóa query: gộp "1,4 mét"/"1.4 m" -> token so sánh được
            # q_robot: lowercase, bỏ dấu, đổi "," -> ".", gộp "X.Y met"/"X.Y m" -> "X.Ym"
            q_robot = q_norm.replace(",", ".")
            q_robot = re.sub(r"(\d)\.(\d)\s*(?:met|m)\b", lambda mm: f"{mm.group(1)}.{mm.group(2)}m", q_robot)
            # Ưu tiên robot model CỤ THỂ (MA####/AR####) hơn brand chung.
            # Ví dụ "yaskawa 1440": chọn MA1440 (từ "1440") thay vì "Yaskawa AR Series".
            matched_specific = None
            matched_brand = None
            for alias in sorted(alias_map.keys(), key=len, reverse=True):
                al = alias.lower()
                if re.search(r"\b" + re.escape(al) + r"\b", q_robot):
                    target = alias_map[alias]
                    if re.match(r"^(MA|AR|MH|EA)\d", str(target)):
                        if matched_specific is None:
                            matched_specific = target
                    elif matched_brand is None:
                        matched_brand = target
            result.robot_model_hint = matched_specific or matched_brand


    # ── Step 5: Fuzzy code candidates ──────────────────────────────────────────

    def _suggest_code_candidates(self, query: str, result: FuzzyResult) -> None:
        """
        Tìm part_no & model_code candidates qua fuzzy match.
        Chỉ trigger nếu query chứa token "code-like" (chữ + số, ≥ MIN_CODE_LEN).
        """
        # Extract code-like tokens
        tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9\-]{2,}\b", query)
        code_tokens = [t for t in tokens if _is_code_like(t) and len(t) >= MIN_CODE_LEN_FOR_FUZZY]

        # BUG-FIX #9: 6-digit Tokin codes (e.g. "003003", "002001") không match regex trên
        # vì bắt đầu bằng số. Add chúng vào code_tokens.
        digit_tokens = re.findall(r"\b\d{6}\b", query)
        code_tokens.extend(digit_tokens)

        if not code_tokens:
            return

        for tok in code_tokens:
            tok_norm = _normalize_for_compare(tok)
            if not tok_norm:
                continue

            # Part_no match
            part_matches = self._fuzzy_match_codes(tok_norm, self._all_part_codes,
                                                  PART_NO_SIM_THRESHOLD)
            for code, sim in part_matches[:MAX_CANDIDATES_PER_TYPE]:
                if (code, sim) not in result.part_no_candidates:
                    result.part_no_candidates.append((code, sim))
                if sim < 1.0 and code.upper() != tok.upper():
                    result.corrections.append(FuzzyCorrection(
                        original=tok, corrected=code, kind="part_no", confidence=sim))

            # Model code match
            model_matches = self._fuzzy_match_codes(tok_norm, self._all_model_codes,
                                                   MODEL_CODE_SIM_THRESHOLD)
            for code, sim in model_matches[:MAX_CANDIDATES_PER_TYPE]:
                if (code, sim) not in result.model_code_candidates:
                    result.model_code_candidates.append((code, sim))
                if sim < 1.0 and code.upper() != tok.upper():
                    result.corrections.append(FuzzyCorrection(
                        original=tok, corrected=code, kind="model_code", confidence=sim))

        # Sort candidates desc by similarity, dedupe
        result.part_no_candidates    = sorted(set(result.part_no_candidates),
                                              key=lambda x: -x[1])[:MAX_CANDIDATES_PER_TYPE]
        result.model_code_candidates = sorted(set(result.model_code_candidates),
                                              key=lambda x: -x[1])[:MAX_CANDIDATES_PER_TYPE]

    def _fuzzy_match_codes(self, target_norm: str,
                           code_pool: Set[str],
                           threshold: float) -> List[Tuple[str, float]]:
        """
        So sánh target_norm với mọi code trong pool, trả về list (code, sim)
        sorted desc, similarity ≥ threshold.

        Optimization: skip codes khác độ dài quá xa (> 30%) — tránh O(N) so toàn pool.
        """
        if not code_pool:
            return []

        target_len = len(target_norm)
        candidates = []
        for code in code_pool:
            code_norm = _normalize_for_compare(code)
            if not code_norm:
                continue
            # Length prefilter
            if abs(len(code_norm) - target_len) > max(2, target_len // 3):
                continue
            # Exact match — short-circuit
            if code_norm == target_norm:
                return [(code, 1.0)]
            sim = _similarity(target_norm, code_norm)
            if sim >= threshold:
                candidates.append((code, sim))

        candidates.sort(key=lambda x: -x[1])
        return candidates


# ══════════════════════════════════════════════════════════════════════════════
# Module-level singleton + convenience function
# ══════════════════════════════════════════════════════════════════════════════

_corrector_instance: Optional[FuzzyCorrector] = None

def get_fuzzy_corrector(ds=None) -> FuzzyCorrector:
    """Lazy singleton — dùng trong retrieval_orchestrator."""
    global _corrector_instance
    if _corrector_instance is None:
        _corrector_instance = FuzzyCorrector(ds=ds)
    return _corrector_instance


def reset_fuzzy_corrector():
    """Test helper — reset singleton."""
    global _corrector_instance
    _corrector_instance = None


def correct(query: str, ds=None) -> FuzzyResult:
    """Shortcut: correct(query) → FuzzyResult."""
    return get_fuzzy_corrector(ds=ds).correct(query)


# ══════════════════════════════════════════════════════════════════════════════
# CLI smoke test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    test_queries = sys.argv[1:] or [
        "tipn350a12",
        "TK308RR",
        "bec han N 350",
        "đầu hàn N 350A 1.2mm",
        "chụp khí WX 500A",
        "túng hàn 350a",       # phonetic
        "MAG350",
        "TK309R1 hệ N",
        "tip n350a 12",
    ]
    corrector = FuzzyCorrector()
    for q in test_queries:
        r = corrector.correct(q)
        print(f"\n>>> {q!r}")
        print(f"    corrected: {r.corrected_query!r}")
        if r.corrections:
            for c in r.corrections:
                print(f"      [{c.kind:13s}] {c.original!r} → {c.corrected!r} (sim={c.confidence:.2f})")
        if r.category_hints:    print(f"    categories:    {r.category_hints}")
        if r.ecosystem_hint:    print(f"    ecosystem:     {r.ecosystem_hint}")
        if r.current_class_hint: print(f"    current_class: {r.current_class_hint}")
        if r.wire_size_hint:    print(f"    wire_size:     {r.wire_size_hint}")
        if r.part_no_candidates: print(f"    part_no_cand:  {r.part_no_candidates[:3]}")
        if r.model_code_candidates: print(f"    model_cand:    {r.model_code_candidates[:3]}")
