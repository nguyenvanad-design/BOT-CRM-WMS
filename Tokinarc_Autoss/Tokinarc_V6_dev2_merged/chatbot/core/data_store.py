# core/data_store.py
# TOKINARC DataStore v1.2 — Single Source of Truth
# =================================================
# v1.2 (2026-05-25): path resolution defensive
#   - Auto-detect tokinarc_data_v*.json (lấy version cao nhất theo lexical sort)
#   - Path(__file__) relative thay vì Windows absolute hardcode
#   - Env var TOKINARC_DATA / TOKINARC_ASSEMBLY priority cao nhất
#   - Windows abs path giữ lại làm fallback cuối cho legacy dev environment
#   - Không cần main.py truyền explicit path — script standalone (eval, test) cũng OK
# UTF-8 NO BOM

from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path
from typing import Any, List, Optional

# ─── Path resolution ──────────────────────────────────────────────────────────
# Search order:
#   1. Env var TOKINARC_DATA / TOKINARC_ASSEMBLY (highest priority)
#   2. <repo_root>/data/tokinarc_data_v*.json (auto-pick latest version)
#   3. Windows legacy: C:\Users\ADMIN\Desktop\botautoss\data\...
#   4. Default fallback path (raises clear error if file missing)

# __file__ = .../core/data_store.py → parent = core/ → parent.parent = repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR_REPO = _REPO_ROOT / "data"
_LEGACY_WIN_DATA_DIR = Path(r"C:\Users\ADMIN\Desktop\botautoss\data")


def _find_latest_data_file(pattern: str = "tokinarc_data_v*.json") -> Optional[str]:
    """
    Auto-detect file data version cao nhất.

    Tìm trong 2 thư mục theo thứ tự:
      1. <repo_root>/data/  (preferred — relative deploy)
      2. C:\\Users\\ADMIN\\Desktop\\botautoss\\data\\  (legacy dev)

    Lexical sort: tokinarc_data_v14.json > v13.json > v11k.json (string compare).
    Returns: absolute path string, hoặc None nếu không tìm thấy.
    """
    for data_dir in (_DATA_DIR_REPO, _LEGACY_WIN_DATA_DIR):
        if not data_dir.exists():
            continue
        candidates: List[Path] = sorted(
            data_dir.glob(pattern),
            key=lambda p: p.name,
            reverse=True,  # cao nhất trước
        )
        if candidates:
            return str(candidates[0])
    return None


def _resolve_data_path() -> str:
    """Resolve final path cho data file — env var > auto-detect > default fallback."""
    env = os.environ.get("TOKINARC_DATA")
    if env:
        return env
    found = _find_latest_data_file("tokinarc_data_v*.json")
    if found:
        return found
    # Final fallback — error rõ ràng khi load nếu file không tồn tại
    return str(_DATA_DIR_REPO / "tokinarc_data_v14.json")


def _resolve_assembly_path() -> str:
    """Resolve assembly_procedures path — env var > auto-detect > default fallback."""
    env = os.environ.get("TOKINARC_ASSEMBLY")
    if env:
        return env
    found = _find_latest_data_file("assembly_procedures_v*.json")
    if found:
        return found
    return str(_DATA_DIR_REPO / "assembly_procedures_v1_3.json")


_DEFAULT_DATA     = _resolve_data_path()
_DEFAULT_ASSEMBLY = _resolve_assembly_path()

# Ecosystem ưu tiên khi không rõ (N phổ biến hơn D)
_ECO_PRIORITY = ["N", "D", "WX"]

# CC banding: khi filter cc X không tìm thấy, expand sang các cc tương đương
# 250A/300A/400A → 350A parts; 450A → 500A parts
_CC_BAND: dict[str, list[str]] = {
    "200A": ["200A", "350A"],
    "250A": ["250A", "350A"],
    "300A": ["300A", "350A"],
    "400A": ["400A", "350A", "500A"],
    "450A": ["450A", "500A"],
}


class TokinarcDataStore:

    def __init__(self,
                 data_path: str = _DEFAULT_DATA,
                 assembly_path: str = _DEFAULT_ASSEMBLY):

        # Track resolved paths for diagnostic + tokinarc_cer._ensure_raw()
        self._data_path     = data_path
        self._assembly_path = assembly_path

        with open(data_path, encoding="utf-8") as f:
            raw = json.load(f)

        self._parts_list      = raw.get("parts", [])
        self._torches_list    = raw.get("torches", [])
        self._consumable_sets = raw.get("consumable_sets", [])
        self._compat_edges    = raw.get("compatibility_edges", [])
        self._tpms            = raw.get("torch_part_mappings", [])
        self._negative_rules  = raw.get("negative_rules", [])
        self._process_edges   = raw.get("process_edges", [])
        self._category_vocab  = raw.get("category_vocabulary", [])
        self._gas_flow_edges  = raw.get("gas_flow_edges", [])
        # v19: typo alias + torch index
        self.fake_pno_aliases: dict = raw.get("fake_pno_aliases", {})
        self.torch_model_index: set = set(raw.get("torch_model_index", []))

        self._assembly: dict = {}
        if assembly_path and Path(assembly_path).exists():
            with open(assembly_path, encoding="utf-8") as f:
                self._assembly = json.load(f)

        self._build_indexes()

        # Log version info — version filename giúp catch lỗi load sai version
        _data_name = Path(data_path).name
        print(f"[DataStore] loaded {_data_name} | "
              f"{len(self.parts)} parts | "
              f"{len(self.torches)} torches | "
              f"{len(self._consumable_sets)} consumable sets | "
              f"{len(self._tpms)} TPMs | "
              f"{len(self._negative_rules)} negative rules")

    # =========================================================================
    # INDEX BUILDER
    # =========================================================================

    def _build_indexes(self):
        self.parts: dict[str, dict] = {
            p["tokin_part_no"]: p
            for p in self._parts_list if p.get("tokin_part_no")
        }
        self.torches: dict[str, dict] = {
            t["model_code"]: t
            for t in self._torches_list if t.get("model_code")
        }

        self.p_alias: dict[str, str] = {}
        self.d_alias: dict[str, str] = {}

        # Model name alias (TKS-RC → 046301, WF-120 → 046401...)
        # Đọc từ field note: "Model: TKS-RC. ..."
        self.model_alias: dict[str, str] = {}
        _MODEL_STATIC = {
            "TKS-RC": "046301", "TKS-RS": "046302",
            "TKS-Z1": "046311", "TKS-Z2": "046312", "TKS-Z3": "046313",
            "WF-120":  "046401", "WF-130": "046402",
            "WF-180":  "046403", "WF-300": "046404",
            "WR-200TC":"046501", "SMART-GLIDE":"047001",
        }
        self.model_alias.update({k.upper(): v for k, v in _MODEL_STATIC.items()})

        # p_model_codes / d_model_codes / o_model_codes alias (e.g. YT-35CE → 022063)
        self.p_model_alias: dict[str, str] = {}  # Panasonic torch model → part_no
        self.d_model_alias: dict[str, str] = {}  # Daihen torch model → part_no
        self.o_model_alias: dict[str, str] = {}  # OTC torch model → part_no
        self.o_part_alias:  dict[str, str] = {}  # OTC spare part no → part_no

        for pno, part in self.parts.items():
            for a in (part.get("p_part_nos") or []):
                self.p_alias[a.upper()] = pno
            for a in (part.get("d_part_nos") or []):
                self.d_alias[a.upper()] = pno
            for a in (part.get("p_model_codes") or []):
                self.p_model_alias[a.upper()] = pno
            for a in (part.get("d_model_codes") or []):
                self.d_model_alias[a.upper()] = pno
            for a in (part.get("o_model_codes") or []):
                self.o_model_alias[a.upper()] = pno
            for a in (part.get("o_part_nos") or []):
                self.o_part_alias[a.upper()] = pno

        self.compat: dict[str, set] = {}
        self.compat_conf: dict[tuple, float] = {}  # (a,b) → edge confidence

        for pno, part in self.parts.items():
            self.compat[pno] = set(part.get("compatible_with") or [])

        for edge in self._compat_edges:
            a = edge.get("from_part")
            b = edge.get("to_part")
            if a and b and "compatible" in edge.get("relation_type", ""):
                self.compat.setdefault(a, set()).add(b)
                self.compat.setdefault(b, set()).add(a)
                conf = edge.get("confidence")
                if conf:
                    self.compat_conf[(a, b)] = float(conf)
                    self.compat_conf[(b, a)] = float(conf)

        self.neg_rules: dict[tuple, list] = {}
        self.neg_part_rules: dict[str, list] = {}
        self._torch_exceptions: dict[str, set] = {}

        for rule in self._negative_rules:
            eco_a = rule.get("from_ecosystem")
            eco_b = rule.get("to_ecosystem")
            if eco_a and eco_b:
                key = (eco_a.upper(), eco_b.upper())
                self.neg_rules.setdefault(key, []).append(rule)
            from_part = rule.get("from_part")
            if from_part:
                self.neg_part_rules.setdefault(from_part, []).append(rule)
            for tm in (rule.get("exception_torch_models") or []):
                self._torch_exceptions.setdefault(tm, set()).add(rule.get("rule_id", ""))
            if rule.get("torch_model") and rule.get("overrides_rules"):
                tm = rule["torch_model"]
                for rid in rule["overrides_rules"]:
                    self._torch_exceptions.setdefault(tm, set()).add(rid)

        self.torch_parts: dict[str, list] = {}
        for tpm in self._tpms:
            tm   = tpm.get("torch_model")
            pnos = tpm.get("part_nos") or []
            if tm:
                lst = self.torch_parts.setdefault(tm, [])
                for pno in pnos:
                    if pno not in lst and pno in self.parts:
                        lst.append(pno)

        for tm, torch in self.torches.items():
            lst = self.torch_parts.setdefault(tm, [])
            for pno in (torch.get("compatible_parts") or []):
                if pno in self.parts and pno not in lst:
                    lst.append(pno)

        self.by_category: dict[str, list] = {}
        for pno, part in self.parts.items():
            cat = part.get("category") or ""
            if cat:
                self.by_category.setdefault(cat, []).append(pno)

        self.cat_vocab: dict[str, str] = {}
        # FIX: Sort vocab entries so InnerTube aliases overwrite Liner aliases
        # when both have "ống lót" prefix — longer/more specific match wins
        _vocab_sorted = sorted(
            self._category_vocab,
            key=lambda e: (e.get("part_category", "") == "InnerTube"),
        )
        for entry in _vocab_sorted:
            cat = entry.get("part_category") or entry.get("en_term") or ""
            if not cat:
                continue
            for term in ([entry.get("vi_term")] +
                         [entry.get("en_term")] +
                         (entry.get("vi_aliases") or [])):
                if term:
                    self.cat_vocab[term.lower()] = cat

        self.by_eco_cc: dict[tuple, list] = {}
        for pno, part in self.parts.items():
            eco = (part.get("ecosystem") or "").upper()
            cc  = (part.get("current_class") or "").upper()
            # Skip UNIVERSAL/ALL — quá rộng, gây noise trong filter
            if eco and cc and eco not in ("UNIVERSAL","HYBRID") and cc != "ALL":
                self.by_eco_cc.setdefault((eco, cc), []).append(pno)

        self.symptom_map: dict[str, dict] = {}
        for ts in (self._assembly.get("troubleshooting") or []):
            sid = ts.get("id", "")
            self.symptom_map[sid] = ts

        self.rep_procedures: dict[str, dict] = {}
        for rp in (self._assembly.get("replacement_procedures") or []):
            self.rep_procedures[rp.get("id", "")] = rp

        self.asm_sequences: dict[str, dict] = {}
        for seq in (self._assembly.get("assembly_sequences") or []):
            eco = seq.get("ecosystem", "")
            if eco:
                self.asm_sequences[eco.upper()] = seq

        # Build torch model fuzzy index: strip hyphens/spaces for matching
        self._torch_fuzzy: dict[str, str] = {}
        for tm in self.torches:
            key = re.sub(r'[-_\s]', '', tm).upper()
            self._torch_fuzzy[key] = tm

        # P3: Text search index cho fallback khi keyword filter miss
        self._text_index: list = []
        self._build_text_index()

    def _build_text_index(self):
        """
        P3 — Build search text index cho mỗi part.
        Dùng cho fallback khi _search_by_desc keyword filter miss.
        """
        import re as _re
        _VI = {
            'béc':'bec','hàn':'han','chụp':'chup','khí':'khi',
            'cách':'cach','điện':'dien','hệ':'he','dài':'dai',
            'thân':'than','giữ':'giu',
        }
        def _nv(s):
            s = (s or '').lower()
            for k,v in _VI.items(): s = s.replace(k,v)
            return s

        for pno, part in self.parts.items():
            ws = part.get('wire_size_mm')
            ws_tokens = ''
            if ws:
                ws_str = str(ws).rstrip('0').rstrip('.')
                ws_tokens = ws_str + ' ' + ws_str.replace('.', '')
            note = _nv(part.get('note') or '')
            raw = (part.get('note') or '') + ' ' + (part.get('display_name_en') or '')
            extra = ' '.join(
                m.lower().replace('-','') + ' ' + m.lower()
                for m in _re.findall(r'HR-?\d+', raw, _re.I)
            )
            name_vi = part.get('display_name_vi') or ''
            # Thêm variant không dấu vào index để match query không dấu
            name_vi_nodiac = TokinarcDataStore._strip_diacritics(name_vi).lower()
            text = ' '.join(filter(None,[
                _nv(name_vi),
                name_vi_nodiac,
                (part.get('display_name_en') or '').lower(),
                note, pno,
                (part.get('category') or '').lower(),
                (part.get('ecosystem') or '').lower(),
                str(part.get('current_class') or '').lower(),
                ws_tokens, extra,
            ]))
            self._text_index.append((part, text))

    def _resolve_category_from_query(self, raw_q: str, cats: list) -> str:
        """
        Disambiguate category từ raw query.
        - 'thân giữ béc' không có 'tipbody'/'tip body' → Tip (intent thực tế VN)
        - 'TipBody'/'tip body' nguyên chữ → TipBody
        - 'ceramic nozzle' không có 'TIG' → Nozzle (MIG context)
        - 'ống lót trong' → InnerTube (không phải Liner)
        """
        q = (raw_q or '').lower()

        if not cats:
            return ''

        raw_cat = cats[0].strip().lower()
        resolved = self.cat_vocab.get(raw_cat) or cats[0]

        # Disambiguation: TipBody vs Tip
        if resolved == 'TipBody':
            explicit_tipbody = any(k in q for k in ('tipbody', 'tip body', 'thân giữ béc loại'))
            if not explicit_tipbody and 'thân giữ béc' in q and 'tipbody' not in q:
                # Khách VN nói "thân giữ béc" thường muốn cả bộ béc
                resolved = 'Tip'

        # Disambiguation: CeramicNozzle vs Nozzle
        if resolved == 'CeramicNozzle':
            if 'tig' not in q and 'collet' not in q and 'tungsten' not in q:
                resolved = 'Nozzle'  # ceramic nozzle trong context MIG = Nozzle

        return resolved

    def _resolve_torch_model(self, model_input: str) -> Optional[str]:
        """Resolve torch model string → canonical key in self.torches.
        Handles: exact, case-insensitive, strip hyphens/spaces.
        """
        if not model_input:
            return None
        if model_input in self.torches:
            return model_input
        upper = model_input.upper()
        for tm in self.torches:
            if tm.upper() == upper:
                return tm
        key = re.sub(r'[-_\s]', '', model_input).upper()
        return self._torch_fuzzy.get(key)

    def _resolve_torch_list(self, models: list) -> list:
        """Resolve list of torch model strings, filter None."""
        return [r for m in (models or []) for r in [self._resolve_torch_model(m)] if r]

    @staticmethod
    def _strip_diacritics(s: str) -> str:
        """Remove Vietnamese diacritics → ASCII lowercase (no unidecode dependency)."""
        import unicodedata
        # Normalize to NFD, keep only ASCII
        nfd = unicodedata.normalize("NFD", s)
        return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

    @staticmethod
    def _norm_noisy(q: str) -> str:
        """P3 — Normalize NOISY query cho text search.
        Xử lý cả: query có dấu, query không dấu, typo phổ biến.
        """
        import re as _re
        # Full Vietnamese diacritic map (common terms)
        _VI_FULL = {
            'béc':'bec','bếc':'bec',
            'hàn':'han',
            'chụp':'chup','chụp':'chup',
            'khí':'khi',
            'cách':'cach',
            'điện':'dien',
            'hệ':'he',
            'dài':'dai',
            'thân':'than',
            'giữ':'giu',
            'ống':'ong',
            'lót':'lot',
            'sứ':'su',
            'chia':'chia',
            'cách điện':'cach dien',
            'thân giữ béc':'than giu bec',
            'ống dẫn':'ong dan',
            'ống lót':'ong lot',
            'súng':'sung',
            'súng hàn':'sung han',
            'ngắn':'ngan',
            'dài':'dai',
            'dây':'day',
            'nhôm':'nhom',
            'đồng':'dong',
        }
        s = q.lower()
        for k, v in _VI_FULL.items():
            s = s.replace(k, v)

        # tipn350a12 → tip n 350a 1.2
        s = _re.sub(
            r'\btip\s*n\s*(\d{3})\s*a\s*(\d{1,2})\b',
            lambda m: (f"tip n {m.group(1)}a "
                       f"{m.group(2)[0]+'.'+m.group(2)[1:] if len(m.group(2))==2 else m.group(2)}"),
            s, flags=_re.I,
        )
        s = _re.sub(r'\bbechan\b', 'bec han', s)
        s = _re.sub(r'\bbecc\b', 'bec', s)
        s = _re.sub(r'\bhr\s*-?\s*350\b', 'hr350', s, flags=_re.I)
        s = _re.sub(r'\bnam\s*ba\s*nam\s*a?\b', '350a', s, flags=_re.I)
        # "he bac" → N ecosystem hint, "he nam" → D
        s = _re.sub(r'\bhe\s*bac\b', 'he n', s, flags=_re.I)
        s = _re.sub(r'\bhe\s*nam\b', 'he d', s, flags=_re.I)
        return s

    def _text_search_fallback(self, query, eco='', cc='', ws=None, cat='', top_k=10):
        """
        P3 — Text search fallback khi _search_by_desc keyword filter miss.
        Respect eco/cc/ws filter cứng để tránh false positive.
        Trả về list[dict] parts, source='text_fallback'.
        """
        import re as _re
        _STOP = {'con','hang','gia','bao','nhieu','roi','luon','tu','van',
                 'can','lay','them','mua','xong','cho','cua','nao','gi','k','ko'}
        q = self._norm_noisy(query)
        # Thêm variant không dấu
        q_nodiac = self._strip_diacritics(q)
        # Merge tokens từ cả 2 variant
        all_tokens = set()
        for _q in (q, q_nodiac):
            for t in _re.split(r'[\s,/\-_]+', _q):
                if len(t) >= 2 and t not in _STOP:
                    all_tokens.add(t)
        tokens = list(all_tokens)
        if not tokens:
            return []
        results = []
        for part, text in self._text_index:
            if eco and (part.get('ecosystem') or '').upper() not in (eco, 'UNIVERSAL', 'HYBRID'):
                continue
            if cc:
                p_cc = (part.get('current_class') or '').upper()
                cc_ok = set(_CC_BAND.get(cc, [cc]))
                if p_cc not in cc_ok and p_cc not in ('ALL', 'VARIES'):
                    continue
            if ws:
                pw = part.get('wire_size_mm')
                if pw is None or abs(float(pw) - ws) > 0.05:
                    continue
            if cat and cat.lower() not in (part.get('category') or '').lower():
                continue
            score = sum(1 for t in tokens if t in text)
            min_score = max(2, len(tokens) // 3)
            if score >= min_score:
                results.append((score, part))
        results.sort(key=lambda x: (
            -x[0],
            not (x[1].get('business') or {}).get('is_priority_sell', False),
            x[1].get('tokin_part_no',''),
        ))
        return [p for _,p in results[:top_k]]

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def query(self, intent: str, entities: dict) -> dict:
        handlers = {
            "LOOKUP":               self._lookup,
            "CONSUMABLE_SET":       self._consumable_set,
            "COMPATIBILITY_CHECK":  self._compat_check,
            "REPLACEMENT":          self._replacement,
            "SEARCH_BY_DESC":       self._search_by_desc,
            "UPSELL":               self._upsell,
            "AGGREGATE":            self._aggregate,
            "COMPARISON":           self._comparison,
            "INSTALLATION":         self._installation,
            "REPAIR":               self._repair,
            "OUT_OF_SCOPE":         lambda e: _fail("OUT_OF_SCOPE"),
            "CLARIFY":              lambda e: _fail("CLARIFY"),
        }
        fn = handlers.get(intent)
        if fn is None:
            return _fail(f"UNKNOWN_INTENT:{intent}")
        try:
            return fn(entities)
        except Exception as ex:
            return _fail(f"HANDLER_ERROR:{ex}")

    # =========================================================================
    # HANDLERS
    # =========================================================================

    def _lookup(self, e: dict) -> dict:
        results = []

        for pno in (e.get("part_nos") or []):
            part = self.parts.get(pno)
            if part:
                results.append(part)

        if not results:
            for pno in (e.get("p_part_nos") or []):
                tokin = self.p_alias.get(pno.upper())
                if tokin:
                    results.append({**self.parts[tokin],
                                    "_resolved_from": pno, "_brand": "Panasonic"})

        if not results:
            for pno in (e.get("d_part_nos") or []):
                tokin = self.d_alias.get(pno.upper())
                if tokin:
                    results.append({**self.parts[tokin],
                                    "_resolved_from": pno, "_brand": "Daihen/OTC"})

        # p_model_codes lookup: YT-35CE, YT-50CS → part_no (Panasonic torch model)
        if not results:
            for code in (e.get("p_model_codes") or []):
                tokin = self.p_model_alias.get(code.upper())
                if tokin:
                    results.append(self.parts[tokin])
            if not results:
                # Try raw_query scan for p_model patterns
                raw_q = (e.get("_raw_query") or "").upper()
                for alias, pno in self.p_model_alias.items():
                    if alias in raw_q:
                        results.append(self.parts[pno])
                        break

        # d_model_codes lookup: WT3500, WTCX-3504 → part_no (Daihen torch model)
        if not results:
            for code in (e.get("d_model_codes") or []):
                tokin = self.d_model_alias.get(code.upper())
                if tokin:
                    results.append(self.parts[tokin])
            if not results:
                raw_q = (e.get("_raw_query") or "").upper()
                for alias, pno in self.d_model_alias.items():
                    if alias in raw_q:
                        results.append(self.parts[pno])
                        break

        # o_model/o_part lookup: OMT-3, 060-430 → part_no (OTC)
        if not results:
            raw_q = (e.get("_raw_query") or "").upper()
            for alias, pno in self.o_model_alias.items():
                if alias in raw_q:
                    results.append(self.parts[pno])
                    break
            if not results:
                for alias, pno in self.o_part_alias.items():
                    if alias in raw_q:
                        results.append(self.parts[pno])
                        break

        # Model alias lookup: TKS-RC, WF-180, WR-200TC → 6-digit code
        if not results:
            raw_q = (e.get("_raw_query") or "").upper()
            for alias, pno in self.model_alias.items():
                if alias in raw_q and pno in self.parts:
                    results.append(self.parts[pno])
                    break

        if not results:
            for tm in (e.get("torch_models") or []):
                torch = self.torches.get(tm)
                if torch:
                    results.append({"_type": "torch", **torch})

        if results:
            return _ok(results[0] if len(results) == 1 else results)

        # FIX #578/#600/#700: LOOKUP không có part_no nhưng có eco+ws → search
        # Trường hợp: "tip he N 1.2 gia bao nhieu", "tư vấn béc 1.2 hệ N rồi báo giá"
        eco = (e.get("ecosystem") or "").upper()
        ws  =  e.get("wire_size")
        if (eco or ws) and not e.get("torch_models"):
            sr = self._search_by_desc(e)
            if sr["success"]:
                return sr

        return _fail("NO_MATCH")

    # ─────────────────────────────────────────────────────────────────────────

    def _consumable_set(self, e: dict) -> dict:
        """
        CONSUMABLE_SET: lookup bộ vật tư tiêu hao.
        FIX v1.1: khi eco=None → thử lần lượt N, D, WX
        """
        eco = (e.get("ecosystem") or "").upper()
        cc  = (e.get("current_class") or "").upper()
        ws  =  e.get("wire_size")

        # Resolve eco+cc từ torch model (fuzzy)
        if e.get("torch_models"):
            resolved_tms = self._resolve_torch_list(e["torch_models"])
            torch = self.torches.get(resolved_tms[0] if resolved_tms else e["torch_models"][0]) or {}
            eco = eco or (torch.get("ecosystem") or "").upper()
            cc  = cc  or (torch.get("current_class") or "").upper()

        # Direct lookup với eco+cc đã biết
        if eco and cc:
            result = self._lookup_consumable_set(eco, cc, ws)
            if result:
                return _ok(self._enrich_consumable_set(result))

        # FIX: eco rỗng → thử tất cả ecosystems theo priority (N trước, D sau)
        elif not eco and cc:
            for try_eco in _ECO_PRIORITY:
                result = self._lookup_consumable_set(try_eco, cc, ws)
                if result:
                    enriched = self._enrich_consumable_set(result)
                    enriched["_eco_inferred"] = True
                    enriched["_inferred_eco"] = try_eco
                    return _ok(enriched)

        # Fallback: TPM parts của torch
        if e.get("torch_models"):
            tm   = e["torch_models"][0]
            pnos = self.torch_parts.get(tm, [])
            if pnos:
                grouped = self._group_torch_parts_by_role(tm, pnos[:20])
                return _ok({"torch_model": tm, "eco": eco, "cc": cc,
                             "source": "tpm", "items": grouped})

        return _fail("NO_CONSUMABLE_SET_FOUND")

    def _lookup_consumable_set(self, eco: str, cc: str, ws=None):
        """Tìm consumable set theo eco+cc, optional wire_size.
        FIX: CC banding — khi không tìm thấy exact match, thử cc tương đương.
        300A/250A → 350A; 450A → 500A
        """
        cc_variants = [cc] + [c for c in _CC_BAND.get(cc, []) if c != cc]
        for try_cc in cc_variants:
            candidates = [
                s for s in self._consumable_sets
                if s.get("ecosystem", "").upper() == eco
                and s.get("torch_current_class", "").upper() == try_cc
            ]
            if candidates:
                chosen = candidates[0]
                if ws and len(candidates) > 1:
                    for s in candidates:
                        if abs((s.get("default_wire_size_mm") or 0) - ws) < 0.05:
                            chosen = s
                            break
                return chosen
        return None

    def _enrich_consumable_set(self, cs: dict) -> dict:
        enriched = []
        for item in (cs.get("items") or []):
            pid  = item.get("part_id")
            info = self.parts.get(pid, {})
            enriched.append({
                **item,
                "display_name_vi": info.get("display_name_vi", ""),
                "category":        info.get("category", ""),
                "ecosystem":       info.get("ecosystem", ""),
            })
        return {**cs, "items": enriched}

    def _group_torch_parts_by_role(self, tm: str, pnos: list) -> list:
        role_map: dict[str, list] = {}
        for tpm in self._tpms:
            if tpm.get("torch_model") != tm:
                continue
            role = tpm.get("part_role", "Other")
            for pno in (tpm.get("part_nos") or []):
                if pno in self.parts:
                    info = self.parts[pno]
                    role_map.setdefault(role, []).append({
                        "part_id":         pno,
                        "part_role":       role,
                        "is_mandatory":    tpm.get("is_mandatory", False),
                        "display_name_vi": info.get("display_name_vi", ""),
                        "category":        info.get("category", ""),
                    })
        result = []
        for role, items in role_map.items():
            result.extend(items)
        return result

    # ─────────────────────────────────────────────────────────────────────────

    def _compat_check(self, e: dict) -> dict:
        part_nos     = e.get("part_nos") or []
        torch_models = e.get("torch_models") or []

        if len(part_nos) >= 2:
            return self._check_two_parts(part_nos[0], part_nos[1],
                                          torch_models[0] if torch_models else None)

        if part_nos and torch_models:
            return self._check_part_torch(part_nos[0], torch_models[0])

        # Sub-case C: ecosystem pair
        eco  = (e.get("ecosystem") or "").upper()
        cats = e.get("categories") or []
        if eco and cats:
            # Check N↔D cross
            other_eco = "D" if eco == "N" else ("N" if eco == "D" else None)
            if other_eco:
                neg = (self.neg_rules.get((eco, other_eco), []) or
                       self.neg_rules.get((other_eco, eco), []))
                if neg:
                    return _ok({
                        "compatible": False,
                        "reason": neg[0].get("incompatibility_reason",
                                             "Khác hệ — không tương thích"),
                        "rule_id": neg[0].get("rule_id"),
                        "ecosystem_a": eco,
                    })
            return _ok({
                "compatible": True,
                "reason": f"Các linh kiện cùng hệ {eco} tương thích với nhau",
            })

        # FIX: WX + N/D → không tương thích
        if "WX" in (e.get("ecosystem") or "").upper():
            return _ok({
                "compatible": False,
                "reason": "Hệ WX dùng linh kiện riêng, không tương thích với hệ N hoặc D",
            })

        return _fail("INSUFFICIENT_ENTITIES")

    def _check_two_parts(self, pno_a: str, pno_b: str,
                          torch_context: Optional[str] = None) -> dict:
        pa = self.parts.get(pno_a)
        pb = self.parts.get(pno_b)
        if not pa:
            return _fail(f"PART_NOT_FOUND:{pno_a}")
        if not pb:
            return _fail(f"PART_NOT_FOUND:{pno_b}")

        eco_a = (pa.get("ecosystem") or "").upper()
        eco_b = (pb.get("ecosystem") or "").upper()
        cat_a = (pa.get("category") or "").upper()
        cat_b = (pb.get("category") or "").upper()

        neg_applicable = []
        for rule in self._negative_rules:
            re_a = (rule.get("from_ecosystem") or "").upper()
            re_b = (rule.get("to_ecosystem") or "").upper()
            rc_a = (rule.get("from_category") or "").upper()
            rc_b = (rule.get("to_category") or "").upper()

            match_fwd = (re_a == eco_a and re_b == eco_b and
                         (not rc_a or rc_a == cat_a) and
                         (not rc_b or rc_b == cat_b))
            match_rev = (re_a == eco_b and re_b == eco_a and
                         (not rc_a or rc_a == cat_b) and
                         (not rc_b or rc_b == cat_a))

            if match_fwd or match_rev:
                exc = rule.get("exception_torch_models") or []
                if torch_context and torch_context in exc:
                    continue
                if torch_context:
                    overridden = self._torch_exceptions.get(torch_context, set())
                    if rule.get("rule_id") in overridden:
                        continue
                neg_applicable.append(rule)

        if neg_applicable:
            rule = neg_applicable[0]
            return _ok({
                "part_a": {"part_no": pno_a, "name": pa.get("display_name_vi", ""),
                           "ecosystem": eco_a, "category": pa.get("category", "")},
                "part_b": {"part_no": pno_b, "name": pb.get("display_name_vi", ""),
                           "ecosystem": eco_b, "category": pb.get("category", "")},
                "compatible": False,
                "reason": rule.get("incompatibility_reason", "Không tương thích"),
                "rule_id": rule.get("rule_id"),
            })

        direct    = ((pno_b in self.compat.get(pno_a, set())) or
                     (pno_a in self.compat.get(pno_b, set())))
        eco_match = (eco_a == eco_b) if (eco_a and eco_b) else None
        compatible = direct or (eco_match is True)

        if direct:
            reason = "Có trong danh sách compatible_with — tương thích trực tiếp"
        elif eco_match is True:
            reason = f"Cùng hệ {eco_a} — tương thích"
        elif eco_match is False:
            reason = f"Khác hệ ({eco_a} vs {eco_b}) — không tương thích"
        else:
            reason = "Không đủ dữ liệu để kết luận"

        return _ok({
            "part_a": {"part_no": pno_a, "name": pa.get("display_name_vi", ""),
                       "ecosystem": eco_a, "category": pa.get("category", "")},
            "part_b": {"part_no": pno_b, "name": pb.get("display_name_vi", ""),
                       "ecosystem": eco_b, "category": pb.get("category", "")},
            "compatible": compatible,
            "reason": reason,
            "ecosystem_match": eco_match,
            "direct_compat": direct,
        })

    def _check_part_torch(self, pno: str, tm: str) -> dict:
        part  = self.parts.get(pno)
        torch = self.torches.get(tm)
        if not part:
            return _fail(f"PART_NOT_FOUND:{pno}")
        if not torch:
            return _fail(f"TORCH_NOT_FOUND:{tm}")

        in_torch_compat = pno in (torch.get("compatible_parts") or [])
        in_part_torches = tm  in (part.get("torch_models") or [])
        in_tpm          = pno in self.torch_parts.get(tm, [])
        compatible      = in_torch_compat or in_part_torches or in_tpm

        sources = []
        if in_torch_compat: sources.append("torch.compatible_parts")
        if in_part_torches:  sources.append("part.torch_models")
        if in_tpm:           sources.append("TPM")

        return _ok({
            "part":  {"part_no": pno, "name": part.get("display_name_vi", ""),
                      "ecosystem": part.get("ecosystem", "")},
            "torch": {"model_code": tm, "current_class": torch.get("current_class", ""),
                      "ecosystem": torch.get("ecosystem", "")},
            "compatible": compatible,
            "reason": ("Tương thích — " + ", ".join(sources)) if compatible
                      else "Không tìm thấy mối liên kết tương thích",
        })

    # ─────────────────────────────────────────────────────────────────────────

    def _replacement(self, e: dict) -> dict:
        results = []
        for pno in (e.get("p_part_nos") or []):
            tokin = self.p_alias.get(pno.upper())
            if tokin and tokin in self.parts:
                results.append({
                    "source_code":   pno,
                    "source_brand":  "Panasonic",
                    "tokin_part_no": tokin,
                    "part_info":     self.parts[tokin],
                })
        for pno in (e.get("d_part_nos") or []):
            tokin = self.d_alias.get(pno.upper())
            if tokin and tokin in self.parts:
                results.append({
                    "source_code":   pno,
                    "source_brand":  "Daihen/OTC",
                    "tokin_part_no": tokin,
                    "part_info":     self.parts[tokin],
                })
        if results:
            return _ok(results[0] if len(results) == 1 else results)
        return _fail("NO_REPLACEMENT_FOUND")

    # ─────────────────────────────────────────────────────────────────────────

    def _search_by_desc(self, e: dict) -> dict:
        eco  = (e.get("ecosystem") or "").upper()
        cc   = (e.get("current_class") or "").upper()
        ws   =  e.get("wire_size")
        cats =  e.get("categories") or []

        cat = ""
        if cats:
            cat = self._resolve_category_from_query(e.get("_raw_query", ""), cats)

        # FIX câu 1/3: khi eco rỗng, không trả WX (hệ đặc biệt, ít khi hỏi chung)
        _raw_q = (e.get("_raw_query") or "").lower()
        _wx_mentioned = any(s in _raw_q for s in ("wx", "water cool", "làm mát nước"))
        # CC banding: expand cc sang các giá trị tương đương khi cần
        cc_accept = set(_CC_BAND.get(cc, [cc])) if cc else set()

        results = []
        for pno, part in self.parts.items():
            p_eco = (part.get("ecosystem") or "").upper()
            if eco and p_eco != eco:
                continue
            # Filter WX khi không được hỏi rõ
            if not eco and p_eco == "WX" and not _wx_mentioned:
                continue
            if cc:
                p_cc = (part.get("current_class") or "").upper()
                if p_cc not in cc_accept and p_cc not in ("ALL", "VARIES"):
                    continue
            if ws:
                pw = part.get("wire_size_mm")
                if pw is None or abs(float(pw) - ws) > 0.05:
                    continue
            if cat:
                pc = (part.get("category") or "").lower()
                if cat.lower() not in pc:
                    continue
            results.append(part)

        results.sort(key=lambda p: (
            not p.get("business", {}).get("is_priority_sell", False),
            p.get("tokin_part_no", "")
        ))

        if results:
            return _ok(results[:20])

        # ── BUG-FIX (post-v15): Filter relaxation khi strict search empty ─────
        # Trước khi rơi xuống text fallback, thử relax từng filter một:
        #   (1) Drop wire_size filter (TungstenElectrode/Liner thường wire=None trong data)
        #   (2) Drop ecosystem filter (eval đôi khi nhầm D=Daihen brand vs D-system)
        #   (3) Drop current_class filter (amperage đôi khi không có exact match)
        # CHỈ relax khi có category — để tránh trả về toàn database.
        if cat and (ws or eco or cc):
            for relax_step in ("drop_wire", "drop_eco", "drop_cc", "cat_only"):
                _ws = ws if relax_step in ("drop_eco","drop_cc") else None if relax_step=="drop_wire" else None
                _eco = eco if relax_step in ("drop_wire","drop_cc") else "" if relax_step=="drop_eco" else ""
                _cc = cc if relax_step in ("drop_wire","drop_eco") else "" if relax_step=="drop_cc" else ""
                if relax_step == "cat_only":
                    _ws, _eco, _cc = None, "", ""
                relaxed = []
                _cc_ok = set(_CC_BAND.get(_cc, [_cc])) if _cc else set()
                for pno, part in self.parts.items():
                    p_eco = (part.get("ecosystem") or "").upper()
                    if _eco and p_eco != _eco:
                        continue
                    if not _eco and p_eco == "WX" and not _wx_mentioned:
                        continue
                    if _cc:
                        p_cc = (part.get("current_class") or "").upper()
                        if p_cc not in _cc_ok and p_cc not in ("ALL", "VARIES"):
                            continue
                    if _ws:
                        pw = part.get("wire_size_mm")
                        if pw is None or abs(float(pw) - _ws) > 0.05:
                            continue
                    pc = (part.get("category") or "").lower()
                    if cat.lower() not in pc:
                        continue
                    relaxed.append(part)
                if relaxed:
                    relaxed.sort(key=lambda p: (
                        not p.get("business", {}).get("is_priority_sell", False),
                        p.get("tokin_part_no", "")
                    ))
                    return {
                        "success": True,
                        "data": relaxed[:20],
                        "reason": f"relaxed_{relax_step}",
                        "source": f"relaxed_{relax_step}",
                    }

        # ── P3: Text search fallback khi keyword filter miss ──────────────────
        # Trigger khi có raw_query — không cần alias cụ thể (no-diacritics query cũng cần fallback)
        raw_q = e.get("_raw_query", "")
        if raw_q:
            fallback = self._text_search_fallback(
                query=raw_q, eco=eco, cc=cc, ws=ws, cat=cat, top_k=10,
            )
            if fallback:
                return {
                    "success": True,
                    "data": fallback,
                    "reason": "text_fallback",
                    "source": "text_fallback",
                }

        return _fail("NO_RESULTS")

    # ─────────────────────────────────────────────────────────────────────────

    def _upsell(self, e: dict) -> dict:
        """UPSELL: da co owned parts, can them gi de du bo."""
        _CONSUMABLE_CATS = {"Tip","Nozzle","Insulator","Orifice","TipBody","Liner","InnerTube","WaveWasher"}

        # Collect owned — resolve P/D alias + raw_codes fallback
        raw_owned = list(e.get("owned_parts") or e.get("part_nos") or [])
        for pno in (e.get("p_part_nos") or []):
            tokin = self.p_alias.get(pno.upper())
            raw_owned.append(tokin if tokin else pno)
        for pno in (e.get("d_part_nos") or []):
            tokin = self.d_alias.get(pno.upper())
            raw_owned.append(tokin if tokin else pno)
        for code in (e.get("raw_codes") or []):
            tokin = self.p_alias.get(code.upper()) or self.d_alias.get(code.upper())
            if tokin:
                raw_owned.append(tokin)
            elif code in self.parts:
                raw_owned.append(code)

        owned = {pno for pno in raw_owned if pno in self.parts}

        # Determine eco + cc
        eco = (e.get("ecosystem") or "").upper()
        cc  = (e.get("current_class") or "").upper()

        if e.get("torch_models"):
            torch = self.torches.get(e["torch_models"][0]) or {}
            eco = eco or (torch.get("ecosystem") or "").upper()
            cc  = cc  or (torch.get("current_class") or "").upper()

        if (not eco or eco == "UNIVERSAL") and owned:
            for pno in owned:
                part  = self.parts.get(pno, {})
                p_eco = (part.get("ecosystem") or "").upper()
                if p_eco and p_eco != "UNIVERSAL":
                    eco = p_eco
                cc = cc or (part.get("current_class") or "").upper()
                if eco and eco != "UNIVERSAL" and cc:
                    break

        if (not eco or eco == "UNIVERSAL") and cc:
            for try_eco in _ECO_PRIORITY:
                cs_r = self._consumable_set({"ecosystem": try_eco, "current_class": cc})
                if cs_r["success"]:
                    eco = try_eco
                    break

        # Fallback: resolve eco/cc tu wire_size + ecosystem trong query
        if (not owned) and (not cc or not eco or eco == "UNIVERSAL"):
            ws = e.get("wire_size")
            q_eco = eco if eco and eco != "UNIVERSAL" else None
            candidates = [
                p for p in self._parts_list
                if p.get("category") == "Tip"
                and (ws is None or abs((p.get("wire_size_mm") or 0) - float(ws)) < 0.01)
                and (q_eco is None or (p.get("ecosystem") or "").upper() == q_eco)
            ]
            if candidates:
                best = candidates[0]
                eco = eco or (best.get("ecosystem") or "").upper()
                cc  = cc  or (best.get("current_class") or "").upper()
                owned.add(best["tokin_part_no"])

        if not eco or eco == "UNIVERSAL" or not cc:
            return _fail("CANNOT_DETERMINE_TARGET_SET")

        cs_r = self._consumable_set({"ecosystem": eco, "current_class": cc, "wire_size": e.get("wire_size")})
        if not cs_r["success"]:
            return _fail("CANNOT_DETERMINE_TARGET_SET")

        cs      = cs_r["data"]
        all_ids = [item["part_id"] for item in (cs.get("items") or [])]
        seen    = set(all_ids)

        for owned_pno in owned:
            for cid in self.compat.get(owned_pno, set()):
                if cid in seen or cid not in self.parts:
                    continue
                p     = self.parts[cid]
                p_eco = (p.get("ecosystem") or "").upper()
                p_cat =  p.get("category", "")
                if (p_eco in (eco, "UNIVERSAL") and
                        len(cid) == 6 and cid.isdigit() and
                        p_cat in _CONSUMABLE_CATS):
                    seen.add(cid)
                    all_ids.append(cid)

        # Detect anchor_category để exclude cùng category khi render
        anchor_categories = set()
        for pno in owned:
            p = self.parts.get(pno, {})
            cat = p.get("category", "")
            if cat:
                anchor_categories.add(cat)

        missing = [
            {
                "part_id":         pid,
                "display_name_vi": self.parts.get(pid, {}).get("display_name_vi", ""),
                "category":        self.parts.get(pid, {}).get("category", ""),
                "part_role":       next((i.get("part_role", "") for i in cs.get("items", [])
                                         if i["part_id"] == pid), ""),
                # FIX: enrich business để hiển thị giá
                "business":        self.parts.get(pid, {}).get("business") or {},
                "ecosystem":       (self.parts.get(pid, {}).get("ecosystem") or "").upper(),
            }
            for pid in all_ids if pid not in owned
        ]

        # Average compat_edge confidence cho missing parts
        _ecs = [self.compat_conf.get((op, m["part_id"]))
                for op in owned for m in missing
                if self.compat_conf.get((op, m["part_id"]))]
        _avg_ec = round(sum(_ecs) / len(_ecs), 3) if _ecs else None

        return _ok({
            "owned":              list(owned),
            "full_set_ids":       all_ids,
            "missing":            missing,
            "set_id":             cs.get("set_id", ""),
            "ecosystem":          eco,
            "current_class":      cc,
            "anchor_categories":  list(anchor_categories),
            "_edge_confidence":   _avg_ec,
        })


    def _aggregate(self, e: dict) -> dict:
        eco  = (e.get("ecosystem") or "").upper()
        cc   = (e.get("current_class") or "").upper()
        cats =  e.get("categories") or []
        cat  = cats[0] if cats else ""

        if cat:
            cat = self.cat_vocab.get(cat.lower(), cat)

        # Detect torch/robot queries
        _raw_q = (e.get("_raw_query") or "").lower()
        _TORCH_SIGNALS = ("súng", "sung", "torch", "máy hàn", "may han",
                          "gun", "súng hàn", "sung han")
        _is_torch_query = (
            any(s in _raw_q for s in _TORCH_SIGNALS)
            or cat.lower() in ("torch", "sung", "súng")
        )

        # Scenario C: Robot compatibility query
        # "robot Yaskawa MA1440 cần súng gì", "AR1440 dùng torch nào"
        _ROBOT_PAT = [
            "ma1440", "ar1440", "ar700", "ar900", "ar1730", "ar2010",
            "hp20", "ms80", "robot yaskawa", "robot fanuc", "robot kuka",
            "robot motoman", "yaskawa robot", "robot arm", "robot han",
            "robot hàn",
        ]
        _robot_model = next((r for r in _ROBOT_PAT if r in _raw_q), None)
        if _robot_model or ("robot" in _raw_q and _is_torch_query):
            # Filter torches có robot_compatibility chứa robot model
            robot_key = _robot_model or ""
            matched = []
            for t in self.torches.values():
                rc = [r.lower() for r in (t.get("robot_compatibility") or [])]
                sensor = t.get("shock_sensor_type", "NONE")
                has_sensor = sensor and sensor != "NONE"
                # Match nếu robot model khớp hoặc có shock sensor (robot-capable)
                if (robot_key and any(robot_key in r for r in rc)) or                    (not robot_key and (has_sensor or t.get("has_shock_sensor"))):
                    matched.append(t)
            if matched:
                matched.sort(key=lambda t: t.get("model_code", ""))
                return _ok({
                    "type":        "robot_compat",
                    "robot_model": _robot_model.upper() if _robot_model else "robot",
                    "count":       len(matched),
                    "torches":     matched[:15],
                })

        if _is_torch_query:
            torches = list(self.torches.values())
            if eco:
                torches = [t for t in torches
                           if (t.get("ecosystem") or "").upper() == eco]
            if cc:
                torches = [t for t in torches
                           if (t.get("current_class") or "").upper() == cc]
            torches.sort(key=lambda t: t.get("model_code", ""))
            return _ok({
                "type":    "torch_list",
                "count":   len(torches),
                "torches": torches[:50],
            })

        if cat:
            pnos = self.by_category.get(cat, [])
            if eco:
                pnos = [p for p in pnos
                        if (self.parts[p].get("ecosystem") or "").upper() in (eco, "UNIVERSAL", "HYBRID")]
            if cc:
                cc_ok = set(_CC_BAND.get(cc, [cc]))
                pnos = [p for p in pnos
                        if (self.parts[p].get("current_class") or "").upper() in cc_ok
                        or (self.parts[p].get("current_class") or "").upper() in ("ALL", "VARIES")]
            parts = [self.parts[p] for p in pnos if p in self.parts]
            return _ok({"category": cat, "count": len(parts), "parts": parts[:50]})

        if eco:
            pnos = []
            for k, v in self.by_eco_cc.items():
                if k[0] == eco and (not cc or k[1] == cc):
                    pnos.extend(v)
            parts = [self.parts[p] for p in pnos if p in self.parts]
            return _ok({"ecosystem": eco, "current_class": cc or "all",
                        "count": len(parts), "parts": parts[:50]})

        return _ok({
            "total_parts":           len(self.parts),
            "total_torches":         len(self.torches),
            "total_consumable_sets": len(self._consumable_sets),
            "categories":            list(self.by_category.keys()),
            "ecosystems":            list({k[0] for k in self.by_eco_cc}),
        })

    # ─────────────────────────────────────────────────────────────────────────

    def _resolve_any_code(self, code: str) -> str:
        """Resolve bất kỳ mã nào → Tokin 6-digit. Thử Tokin → P → D → O."""
        c = code.upper()
        if code in self.parts:
            return code
        return (self.p_alias.get(c) or
                self.d_alias.get(c) or
                self.o_part_alias.get(c) or
                code)

    def _comparison(self, e: dict) -> dict:
        torch_models = e.get("torch_models") or []

        # Collect tất cả codes từ mọi field, resolve về Tokin
        raw_codes = list(e.get("part_nos") or [])
        for pno in (e.get("p_part_nos") or []):
            raw_codes.append(pno)
        for pno in (e.get("d_part_nos") or []):
            raw_codes.append(pno)
        for pno in (e.get("raw_codes") or []):
            raw_codes.append(pno)

        part_nos = []
        for code in raw_codes:
            resolved = self._resolve_any_code(code)
            if resolved not in part_nos:
                part_nos.append(resolved)

        if len(part_nos) >= 2:
            a = self.parts.get(part_nos[0])
            b = self.parts.get(part_nos[1])
            if a and b:
                return _ok({"type": "part_vs_part", "item_a": a, "item_b": b})

        if len(torch_models) >= 2:
            a = self.torches.get(torch_models[0])
            b = self.torches.get(torch_models[1])
            if a and b:
                return _ok({"type": "torch_vs_torch", "item_a": a, "item_b": b})

        eco = (e.get("ecosystem") or "").upper()
        if eco:
            sr = self._search_by_desc(e)
            return _ok({"type": "ecosystem_query", "ecosystem": eco,
                        "parts": sr.get("data")})

        return _fail("INSUFFICIENT_ITEMS_TO_COMPARE")

    # ─────────────────────────────────────────────────────────────────────────

    def _installation(self, e: dict) -> dict:
        eco = (e.get("ecosystem") or "").upper()

        # Map category → parts thường thay thế (để Gemini mention mã)
        _INSTALL_PARTS = {
            "Tip":     ["002001","002002","002003","002005","002017"],
            "tip":     ["002001","002002","002003","002005","002017"],
            "Nozzle":  ["001002","033203","001001"],
            "nozzle":  ["001002","033203","001001"],
            "Liner":   ["016051","016076","016126"],
            "liner":   ["016051","016076","016126"],
            "Insulator":["004002","004001"],
            "insulator":["004002","004001"],
            "TipBody": ["036001","016403"],
            "tipbody": ["036001","016403"],
        }

        cats = e.get("categories") or []
        # Lấy related parts theo category được hỏi
        related_parts = []
        for cat in cats[:2]:
            pnos = _INSTALL_PARTS.get(cat, [])
            related_parts.extend([self.parts[p] for p in pnos if p in self.parts])
        # Fallback: tip + nozzle là hay hỏi nhất
        if not related_parts:
            for p in ["002001","002002","002003","002005","004002","004001"]:
                if p in self.parts:
                    related_parts.append(self.parts[p])

        def _adapt_sequence(seq: dict) -> dict:
            steps = seq.get("steps") or []
            adapted_steps = []
            for s in steps:
                action = s.get("action") or ""
                note   = s.get("note") or ""
                desc   = f"{action} — {note}" if note else action
                adapted_steps.append({**s, "description_vi": desc})
            torque_raw = self._assembly.get("torque_specs") or []
            torque_dict = {}
            if isinstance(torque_raw, list):
                for t in torque_raw:
                    cat = t.get("category") or t.get("component", "")
                    if cat:
                        torque_dict[cat] = t.get("value_display", "")
            elif isinstance(torque_raw, dict):
                torque_dict = torque_raw
            return {**seq, "steps": adapted_steps, "torque_specs": torque_dict}

        if eco and eco in self.asm_sequences:
            return _ok({"type": "assembly_sequence",
                        "data": _adapt_sequence(self.asm_sequences[eco]),
                        "related_parts": related_parts})

        if cats:
            cat = cats[0].lower()
            proc_map = {
                "tip body":   "rep_tip_body",
                "tipbody":    "rep_tip_body",
                "liner":      "rep_liner",
                "inner tube": "rep_inner_tube",
                "innertube":  "rep_inner_tube",
                "nozzle":     "rep_nozzle",
                "tip":        "rep_tip",
            }
            proc_id = proc_map.get(cat)
            if proc_id and proc_id in self.rep_procedures:
                proc = self.rep_procedures[proc_id]
                steps = proc.get("steps") or []
                adapted = [{**s, "description_vi": s.get("action", "")} for s in steps]
                return _ok({"type": "replacement_procedure",
                            "data": {**proc, "steps": adapted},
                            "related_parts": related_parts})

        default_seq = self.asm_sequences.get("N") or (
            list(self.asm_sequences.values())[0] if self.asm_sequences else {}
        )
        torque_raw = self._assembly.get("torque_specs") or []
        torque_dict = {}
        if isinstance(torque_raw, list):
            for t in torque_raw:
                cat = t.get("category") or t.get("component", "")
                if cat:
                    torque_dict[cat] = t.get("value_display", "")
        return _ok({
            "type": "general_installation",
            "assembly_sequences": list(self.asm_sequences.values()),
            "torque_specs": torque_dict,
            "warnings": self._assembly.get("warnings", []),
            "data": _adapt_sequence(default_seq) if default_seq else {},
            "related_parts": related_parts,
        })

    # ─────────────────────────────────────────────────────────────────────────

    def _repair(self, e: dict) -> dict:
        symptom_keywords = {
            "wire feeding":    "ts_wire_feeding_unstable",
            "kẹt dây":         "ts_wire_feeding_unstable",
            "ket day":         "ts_wire_feeding_unstable",
            "cap khong deu":   "ts_wire_feeding_unstable",
            "cấp không đều":   "ts_wire_feeding_unstable",
            "day khong chay":  "ts_wire_feeding_unstable",
            "rò khí":          "ts_gas_leaking",
            "ro khi":          "ts_gas_leaking",
            "gas leak":        "ts_gas_leaking",
            "thoat khi":       "ts_gas_leaking",
            "spatter":         "ts_excessive_spatter",
            "bắn tóe":         "ts_excessive_spatter",
            "ban toe":         "ts_excessive_spatter",
            "ban nhieu":       "ts_excessive_spatter",
            "bắn nhiều":       "ts_excessive_spatter",
            "bắn bi":          "ts_excessive_spatter",
            "ban bi":          "ts_excessive_spatter",
            "tóe":             "ts_excessive_spatter",
            "toe nhieu":       "ts_excessive_spatter",
            "arc":             "ts_arc_unstable",
            "hồ quang":        "ts_arc_unstable",
            "ho quang":        "ts_arc_unstable",
            "chap dien":       "ts_arc_unstable",
            "không ổn định":   "ts_arc_unstable",
            "khong on dinh":   "ts_arc_unstable",
            "on dinh":         "ts_arc_unstable",
            "mối hàn xấu":     "ts_arc_unstable",
            "moi han xau":     "ts_arc_unstable",
            "tiếng nổ":        "ts_arc_unstable",
            "tieng no":        "ts_arc_unstable",
            "liner":           "ts_wire_feeding_unstable",
            "kẹt":             "ts_wire_feeding_unstable",
            "ket":             "ts_wire_feeding_unstable",
            # ── từ assembly_procedures_v1_3 ──────────────────────────────
            "chạm mass":       "ts_ground_fault",
            "cham mass":       "ts_ground_fault",
            "ground fault":    "ts_ground_fault",
            "rò điện":         "ts_ground_fault",
            "ro dien":         "ts_ground_fault",
            "giật điện":       "ts_ground_fault",
            "giat dien":       "ts_ground_fault",
            "ren hỏng":        "ts_torch_body_damaged_threads",
            "ren hong":        "ts_torch_body_damaged_threads",
            "stripped thread": "ts_torch_body_damaged_threads",
            "thân súng hỏng":  "ts_torch_body_damaged_threads",
            "than sung hong":  "ts_torch_body_damaged_threads",
            "sứ vỡ":           "ts_center_ceramic_cracked",
            "su vo":           "ts_center_ceramic_cracked",
            "ceramic nứt":     "ts_center_ceramic_cracked",
            "ceramic nut":     "ts_center_ceramic_cracked",
            "sứ định tâm":     "ts_center_ceramic_cracked",
            "su dinh tam":     "ts_center_ceramic_cracked",
        }

        # Normalize query để match cả có dấu và không dấu
        import unicodedata as _ud
        def _strip(s):
            return "".join(c for c in _ud.normalize("NFD", s) if _ud.category(c) != "Mn")
        query_lower = (e.get("_raw_query") or "").lower()
        query_nodiac = _strip(query_lower)

        matched_ts = None
        for kw, ts_id in symptom_keywords.items():
            kw_nodiac = _strip(kw)
            if (kw in query_lower or kw_nodiac in query_nodiac) and ts_id in self.symptom_map:
                matched_ts = self.symptom_map[ts_id]
                break

        # Symptom → part_nos map
        SYMPTOM_PARTS: dict = {
            "ts_excessive_spatter":         ["001002","002001","002003","003002","004002"],
            "ts_wire_feeding_unstable":     ["016076","016077","016051","016503","036001","002001"],
            "ts_arc_unstable":              ["001002","002001","003002","004002","036001"],
            "ts_gas_leaking":               ["001002","003002","004002","016051","033203"],
            "ts_torch_body_damaged_threads":["036001","036003","016051","016076"],
            "ts_center_ceramic_cracked":    ["004002","004001","003002","003001"],
            "ts_ground_fault":              ["004002","004001","036001","016051"],
        }
        # Default parts khi không match symptom cụ thể (parts hay hỏng nhất)
        DEFAULT_REPAIR_PARTS = ["001002","002001","002003","003002","004002","036001"]

        cats = e.get("categories") or []
        related_parts = []

        # Priority: lấy parts từ symptom map trước
        if matched_ts:
            ts_id = matched_ts.get("id", "")
            symptom_pnos = SYMPTOM_PARTS.get(ts_id, DEFAULT_REPAIR_PARTS)
            if e.get("torch_models"):
                tm = e["torch_models"][0]
                torch_pnos = set(self.torch_parts.get(tm, []))
                symptom_pnos = [p for p in symptom_pnos if p in torch_pnos] or symptom_pnos
            related_parts = [self.parts[p] for p in symptom_pnos if p in self.parts]

        # Fallback 1: từ categories
        if not related_parts:
            for cat in cats[:2]:
                cat_norm = self.cat_vocab.get(cat.lower(), cat)
                pnos = self.by_category.get(cat_norm, [])
                if e.get("torch_models"):
                    tm = e["torch_models"][0]
                    torch_pnos = set(self.torch_parts.get(tm, []))
                    pnos = [p for p in pnos if p in torch_pnos]
                related_parts.extend([self.parts[p] for p in pnos[:5] if p in self.parts])

        # Fallback 2: dùng default parts nếu vẫn trống
        if not related_parts:
            related_parts = [self.parts[p] for p in DEFAULT_REPAIR_PARTS if p in self.parts]

        # Adapter: map assembly_procedures field names → pipeline_v6 template fields
        # File dùng: symptom (str), likely_causes (list[str]), recommended_action (str)
        # Template đọc: symptom_vi, causes (list), actions (list)
        adapted_ts = None
        if matched_ts:
            ra = matched_ts.get("recommended_action") or ""
            adapted_ts = {
                "symptom_vi": matched_ts.get("symptom", ""),
                "causes":     matched_ts.get("likely_causes", []),
                "actions":    [a.strip() for a in ra.split(".") if a.strip()] if ra else [],
                "_raw":       matched_ts,
            }

        return _ok({
            "troubleshooting": adapted_ts,
            "related_parts":   related_parts,
            "all_troubleshooting": list(self.symptom_map.values()) if not matched_ts else [],
        })


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ok(data: Any) -> dict:
    return {"success": True, "data": data, "reason": ""}

def _fail(reason: str) -> dict:
    return {"success": False, "data": None, "reason": reason}


# ─── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[TokinarcDataStore] = None

def get_data_store(data_path: str = _DEFAULT_DATA,
                   assembly_path: str = _DEFAULT_ASSEMBLY) -> TokinarcDataStore:
    global _instance
    if _instance is None:
        _instance = TokinarcDataStore(data_path, assembly_path)
    return _instance

