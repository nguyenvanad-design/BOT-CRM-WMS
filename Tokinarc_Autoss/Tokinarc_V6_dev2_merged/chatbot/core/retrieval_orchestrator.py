# core/retrieval_orchestrator.py
# TOKINARC Retrieval Orchestrator — Tier 1
# =========================================
# Wire 4 stage Tier 1 retrieval theo thứ tự:
#   Stage 1 — FuzzyCorrector  : sửa typo, boundary, alias → structured hints
#   Stage 2 — Exact match     : part_no candidates từ fuzzy, direct DataStore lookup
#   Stage 3 — Structured search: hints (eco, cc, wire, cat) → _search_by_desc → BM25 rerank
#   Stage 4 — Text fallback   : _text_search_fallback raw query → BM25 rerank
#
# BM25 rerank: chỉ Stage 3+4, lazy-load singleton, safe fallback nếu chưa init.
#
# Dùng trong:
#   - tool_wrappers.search_parts() gọi retrieve() thay vì gọi DataStore trực tiếp
#   - retrieval_eval.py chạy benchmark eval_700
#   - V2 orchestrator optional pre-pass trước khi gọi Gemini
#
# Output: RetrievalResult với ranked parts + metadata cho confidence_layer
#
# UTF-8 NO BOM

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("tokinarc.retrieval_orchestrator")


# ══════════════════════════════════════════════════════════════════════════════
# Result dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RetrievalResult:
    """
    Output của RetrievalOrchestrator.retrieve().

    Attributes:
        parts          : ranked list of part dicts (max top_k)
        stage          : stage nào hit — "exact" | "structured" | "text" | "empty"
        fuzzy_applied  : FuzzyResult đã áp dụng (None nếu không có fuzzy_corrector)
        corrections    : list correction text ngắn gọn cho logging
        filters_applied: filters đã dùng trong structured search
        total_found    : số kết quả trước khi cap top_k
        latency_ms     : tổng thời gian
        query_used     : query sau fuzzy correction
    """
    parts:           List[dict]      = field(default_factory=list)
    stage:           str             = "empty"
    fuzzy_applied:   Any             = None   # FuzzyResult | None
    corrections:     List[str]       = field(default_factory=list)
    filters_applied: Dict[str, Any]  = field(default_factory=dict)
    total_found:     int             = 0
    latency_ms:      float           = 0.0
    query_used:      str             = ""
    match_type:      str             = ""   # "exact_alias_p"|"exact_alias_d"|"exact_tokin"|"exact_model_alias"|"exact_torch"|""
    ds_result:       Optional[dict]  = None  # pre-built ds_result dict for pipeline_v7 tier 1b

    @property
    def success(self) -> bool:
        return bool(self.parts)

    def to_dict(self) -> dict:
        return {
            "success":         self.success,
            "parts":           self.parts,
            "stage":           self.stage,
            "total":           self.total_found,
            "filters_applied": self.filters_applied,
            "latency_ms":      round(self.latency_ms, 1),
            "query_used":      self.query_used,
            "corrections":     self.corrections,
        }


# ══════════════════════════════════════════════════════════════════════════════
# RetrievalOrchestrator
# ══════════════════════════════════════════════════════════════════════════════

class RetrievalOrchestrator:
    """
    Tier 1 retrieval pipeline.

    Usage:
        orch = RetrievalOrchestrator(ds=data_store)
        result = orch.retrieve(
            query="tip N 350A 1.2mm",
            ecosystem="N",
            current_class="350A",
            wire_size_mm=1.2,
            category="Tip",
            top_k=10,
        )
        # result.parts → list of part dicts, result.stage → "exact"|"structured"|"text"

    Priority:
        1. Exact part_no match (từ fuzzy_corrector candidates + raw query tokens)
        2. Structured search (eco + cc + wire + cat filter)
        3. Text fallback (_text_search_fallback)
    """

    def __init__(self, ds=None, fuzzy_corrector=None):
        self._ds = ds
        self._fc = fuzzy_corrector
        self._initialized = False

    # ── Lazy getters ────────────────────────────────────────────────────────────

    @property
    def bm25(self):
        """Lazy BM25 reranker — tự init nếu chưa có, None nếu lỗi."""
        try:
            from core.bm25_reranker import get_bm25_reranker
            bm25 = get_bm25_reranker()
            return bm25
        except RuntimeError:
            # Chưa init với parts_list → tự init từ DataStore
            try:
                from core.bm25_reranker import get_bm25_reranker
                parts_list = list(self.ds.parts.values())
                return get_bm25_reranker(parts_list=parts_list)
            except Exception as e2:
                import logging
                logging.getLogger("tokinarc.retrieval_orchestrator").debug(f"BM25 auto-init failed: {e2}")
                return None
        except Exception:
            return None

    @property
    def ds(self):
        if self._ds is None:
            from data_store import get_data_store
            self._ds = get_data_store()
        return self._ds

    @property
    def fc(self):
        if self._fc is None:
            try:
                from fuzzy_corrector import get_fuzzy_corrector
                self._fc = get_fuzzy_corrector(ds=self._ds)
            except Exception as e:
                log.warning(f"[RetrievalOrch] FuzzyCorrector unavailable: {e}")
                self._fc = None
        return self._fc

    # ── Main API ────────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query:          str,
        ecosystem:      Optional[str]   = None,
        current_class:  Optional[str]   = None,
        wire_size_mm:   Optional[float] = None,
        category:       Optional[str]   = None,
        top_k:          int             = 15,
        intent_hint:    Optional[str]   = None,
    ) -> RetrievalResult:
        """
        Chạy full Tier 1 pipeline. Trả về sau stage đầu tiên có kết quả.

        Args:
            query:         User query (raw hoặc đã normalize)
            ecosystem:     "N" | "D" | "WX" | "TIG" | None
            current_class: "350A" | "500A" | None
            wire_size_mm:  1.2 | 0.9 | None
            category:      "Tip" | "Nozzle" | None
            top_k:         Max results

        Returns:
            RetrievalResult
        """
        t0 = time.perf_counter()
        result = RetrievalResult(query_used=query)

        # ── Step 1: Fuzzy correction ──────────────────────────────────────────
        fuzzy = None
        corrected_query = query
        if query and query.strip():
            try:
                fuzzy = self.fc.correct(query) if self.fc else None
            except Exception as e:
                log.debug(f"[RetrievalOrch] fuzzy error: {e}")

        if fuzzy:
            corrected_query = fuzzy.corrected_query or query
            result.fuzzy_applied = fuzzy
            result.query_used    = corrected_query
            result.corrections   = [
                f"{c.kind}: {c.original!r}→{c.corrected!r}"
                for c in fuzzy.corrections
            ]
            # Merge hints: fuzzy wins only if caller didn't provide
            ecosystem     = ecosystem     or fuzzy.ecosystem_hint
            current_class = current_class or fuzzy.current_class_hint
            wire_size_mm  = wire_size_mm  or fuzzy.wire_size_hint
            if not category and fuzzy.category_hints:
                category = fuzzy.category_hints[0]

        # ── Step 2: Exact match ───────────────────────────────────────────────
        exact_parts = self._stage_exact(corrected_query, fuzzy)
        if exact_parts:
            result.parts       = exact_parts[:top_k]
            result.total_found = len(exact_parts)
            result.stage       = "exact"
            result.latency_ms  = (time.perf_counter() - t0) * 1000
            # Populate match_type for pipeline_v7 tier 1b
            if intent_hint in ("LOOKUP", "REPLACEMENT"):
                p0 = exact_parts[0]
                if p0.get("_resolved_from"):
                    src = p0["_resolved_from"].upper()
                    ds = self.ds
                    if src in getattr(ds, "p_alias", {}):
                        result.match_type = "exact_alias_p"
                    elif src in getattr(ds, "d_alias", {}):
                        result.match_type = "exact_alias_d"
                    elif src in getattr(ds, "p_model_alias", {}) or src in getattr(ds, "d_model_alias", {}):
                        result.match_type = "exact_model_alias"
                    else:
                        result.match_type = "exact_tokin"
                else:
                    result.match_type = "exact_tokin"
                # Build ds_result dict compatible with pipeline_v7
                result.ds_result = {
                    "success": True,
                    "data": p0,
                    "reason": "OK",
                    "source": "retrieval_orch",
                }
            log.info(f"[RetrievalOrch] exact hit: {len(result.parts)} parts "
                     f"latency={result.latency_ms:.1f}ms match_type={result.match_type!r}")
            return result

        # ── Step 2b: Consumable Set ───────────────────────────────────────────
        cs_parts = self._stage_consumable_set(corrected_query, fuzzy, top_k)
        if cs_parts:
            result.parts = cs_parts[:top_k]; result.total_found = len(cs_parts)
            result.stage = "consumable_set"
            result.latency_ms = (time.perf_counter() - t0) * 1000
            log.info(f"[RetrievalOrch] consumable_set hit: {len(result.parts)}")
            return result

        # ── Step 2c: Upsell ───────────────────────────────────────────────────
        up_parts = self._stage_upsell(corrected_query, fuzzy, top_k)
        if up_parts:
            result.parts = up_parts[:top_k]; result.total_found = len(up_parts)
            result.stage = "upsell"
            result.latency_ms = (time.perf_counter() - t0) * 1000
            log.info(f"[RetrievalOrch] upsell hit: {len(result.parts)}")
            return result

        # ── Step 3: Structured search ─────────────────────────────────────────
        struct_parts, filters = self._stage_structured(
            corrected_query, ecosystem, current_class, wire_size_mm, category, top_k,
        )
        if struct_parts:
            # Stage 3 đã filter chính xác (eco+cc+wire+cat) → giữ thứ tự gốc
            # BM25 không cải thiện khi đã có structured filter
            result.parts         = struct_parts[:top_k]
            result.total_found   = len(struct_parts)
            result.stage         = "structured"
            result.filters_applied = filters
            result.latency_ms    = (time.perf_counter() - t0) * 1000
            log.info(f"[RetrievalOrch] structured hit: {len(result.parts)} parts filters={filters} latency={result.latency_ms:.1f}ms")
            return result

        # ── Step 3b: FAISS semantic fallback ─────────────────────────────────
        faiss_parts = self._stage_faiss(
            corrected_query, ecosystem, current_class, category, top_k,
        )
        if faiss_parts:
            if len(faiss_parts) > 1 and corrected_query.strip():
                bm25 = self.bm25
                if bm25:
                    try:
                        ranked = bm25.rerank(corrected_query, faiss_parts, top_k=top_k * 2)
                        faiss_parts = [p for _, p in ranked] if ranked and isinstance(ranked[0], tuple) else faiss_parts
                    except Exception:
                        pass
            result.parts       = faiss_parts[:top_k]
            result.total_found = len(faiss_parts)
            result.stage       = "faiss"
            result.filters_applied = filters
            result.latency_ms  = (time.perf_counter() - t0) * 1000
            log.info(f"[RetrievalOrch] faiss hit: {len(result.parts)} parts latency={result.latency_ms:.1f}ms")
            return result

        # ── Step 4: Text fallback ─────────────────────────────────────────────
        text_parts = self._stage_text(
            corrected_query, ecosystem, current_class, wire_size_mm, category, top_k,
        )
        if text_parts:
            # BM25 rerank Stage 4
            if len(text_parts) > 1 and corrected_query.strip():
                bm25 = self.bm25
                if bm25:
                    try:
                        text_parts = bm25.rerank(corrected_query, text_parts, top_k=top_k * 2)
                        text_parts = [p for _, p in text_parts] if text_parts and isinstance(text_parts[0], tuple) else text_parts
                    except Exception as e:
                        log.debug(f"[RetrievalOrch] BM25 rerank stage4 skip: {e}")
            result.parts       = text_parts[:top_k]
            result.total_found = len(text_parts)
            result.stage       = "text"
            result.latency_ms  = (time.perf_counter() - t0) * 1000
            log.info(f"[RetrievalOrch] text fallback: {len(result.parts)} parts "
                     f"bm25={'on' if self.bm25 else 'off'} latency={result.latency_ms:.1f}ms")
            return result

        # ── Step 4b: Comparison ──────────────────────────────────────────────
        comp_parts = self._stage_comparison(corrected_query, fuzzy, top_k)
        if comp_parts:
            result.parts = comp_parts[:top_k]; result.total_found = len(comp_parts)
            result.stage = "comparison"
            result.latency_ms = (time.perf_counter() - t0) * 1000
            log.info(f"[RetrievalOrch] comparison hit: {len(result.parts)}")
            return result

        result.latency_ms = (time.perf_counter() - t0) * 1000
        log.info(f"[RetrievalOrch] no results for {query!r} "
                 f"(eco={ecosystem}, cc={current_class}) latency={result.latency_ms:.1f}ms")
        return result

    # ── Stage implementations ───────────────────────────────────────────────────

    def _stage_exact(
        self,
        query:  str,
        fuzzy,
    ) -> List[dict]:
        """
        Stage 2: Exact part_no lookup.

        Sources (theo thứ tự):
        A. FuzzyCorrector.part_no_candidates (đã fuzzy-match với DataStore index)
        B. FuzzyCorrector.model_code_candidates → lookup parts cho torch model
        C. Token extraction trực tiếp từ query (6-digit code, TK-xxx pattern)
        """
        ds = self.ds
        found: List[dict] = []
        seen: set = set()

        def _add(pno: str) -> bool:
            """Lookup canonical part + cross-brand alias."""
            pno_upper = pno.upper().strip()
            if pno_upper in seen:
                return False

            # Direct canonical lookup
            part = ds.parts.get(pno_upper) or ds.parts.get(pno)
            if part:
                seen.add(pno_upper)
                found.append(part)
                return True

            # Cross-brand alias lookup
            for alias_dict in (ds.p_alias, ds.d_alias):
                tokin = alias_dict.get(pno_upper)
                if tokin and tokin not in seen:
                    part = ds.parts.get(tokin)
                    if part:
                        seen.add(tokin)
                        found.append({**part, "_resolved_from": pno})
                        return True

            return False

        # A. FuzzyCorrector candidates
        if fuzzy:
            for pno, sim in (fuzzy.part_no_candidates or []):
                if sim >= 0.80:
                    _add(pno)

            # B. Model code → lookup via p_model_alias / d_model_alias
            for mc, sim in (fuzzy.model_code_candidates or []):
                if sim < 0.80:
                    continue
                mc_upper = mc.upper()
                for alias_dict in (
                    getattr(ds, "p_model_alias", {}),
                    getattr(ds, "d_model_alias", {}),
                    getattr(ds, "o_model_alias", {}),
                ):
                    tokin = alias_dict.get(mc_upper)
                    if tokin and tokin not in seen:
                        part = ds.parts.get(tokin)
                        if part:
                            seen.add(tokin)
                            found.append({**part, "_resolved_from": mc})

        # C. Token extraction từ query — 6-digit codes + TK/MAG/MIG/TL pattern
        import re
        tokens = re.findall(
            r'\b(?:[A-Z]{2,6}-\d{2,4}[A-Z0-9]{0,3}|\d{6})\b',
            query.upper(),
        )
        for tok in tokens:
            _add(tok)

        return found

    def _stage_structured(
        self,
        query:          str,
        ecosystem:      Optional[str],
        current_class:  Optional[str],
        wire_size_mm:   Optional[float],
        category:       Optional[str],
        top_k:          int,
    ) -> Tuple[List[dict], dict]:
        """
        Stage 3: Structured filter search.
        Gọi DataStore._search_by_desc() với entities dict chuẩn.
        """
        ds = self.ds
        entities: dict = {
            "_raw_query": query,
        }
        filters: dict  = {}

        if ecosystem:
            entities["ecosystem"] = ecosystem.upper()
            filters["ecosystem"]  = ecosystem.upper()
        if current_class:
            entities["current_class"] = current_class.upper()
            filters["current_class"]  = current_class.upper()
        if wire_size_mm is not None:
            entities["wire_size"] = wire_size_mm
            filters["wire_size_mm"] = wire_size_mm
        if category:
            entities["categories"] = [category]
            filters["category"] = category

        # Cần ít nhất 1 filter meaningful để tránh trả toàn bộ database
        if not filters and not query.strip():
            return [], {}

        try:
            r = ds._search_by_desc(entities)
            if r.get("success"):
                data = r.get("data") or []
                if isinstance(data, dict) and data.get("tokin_part_no"):
                    data = [data]
                if isinstance(data, list) and data:
                    # Fix: post-filter wire_size dùng _wire_size_matches (hỗ trợ range dict/str)
                    if wire_size_mm is not None:
                        data = [
                            p for p in data
                            if self._wire_size_matches(p, wire_size_mm)
                        ] or data  # fallback về unfiltered nếu filter quá chặt
                    return data, filters
        except Exception as e:
            log.warning(f"[RetrievalOrch] structured search error: {e}")

        return [], {}

    def _stage_text(
        self,
        query:         str,
        ecosystem:     Optional[str],
        current_class: Optional[str],
        wire_size_mm:  Optional[float],
        category:      Optional[str],
        top_k:         int,
    ) -> List[dict]:
        """
        Stage 4: Raw text fallback.
        Gọi DataStore._text_search_fallback() với query đã normalize.
        """
        if not query.strip():
            return []
        ds = self.ds
        cat_str = ""
        if category:
            # Normalize category → vocab key
            cat_str = ds.cat_vocab.get(category.lower(), category)
        try:
            return ds._text_search_fallback(
                query = query,
                eco   = (ecosystem or "").upper(),
                cc    = (current_class or "").upper(),
                ws    = wire_size_mm,
                cat   = cat_str,
                top_k = top_k,
            )
        except Exception as e:
            log.warning(f"[RetrievalOrch] text fallback error: {e}")
            return []


    def _stage_consumable_set(self, query, fuzzy, top_k):
        """Stage CS: torch model → TPM parts + consumable set items."""
        import re as _re
        ds = self.ds

        torch_model = None
        if fuzzy:
            for mc, sim in (fuzzy.model_code_candidates or []):
                if sim >= 0.75:
                    torch_model = mc
                    break

        if not torch_model:
            m = _re.search(
                r'\b((?:TK|TL|TLA|TCC|TR|ACC|CSL|CSH|CP|WX|YMSA|YMXA|YMENS|SRCT)'
                r'-\d{2,4}[A-Z0-9-]*)',
                query.upper(),
            )
            if m:
                torch_model = m.group(1)

        cs_keywords = ('bộ','set','tiêu hao','vật tư','linh kiện','consumable',
                       'cần những gì','cần mua gì','bộ đồ')
        is_cs_query = any(kw in query.lower() for kw in cs_keywords)

        if not torch_model and not is_cs_query:
            return []

        found: List[dict] = []
        seen: set = set()

        if torch_model:
            for pno in ds.torch_parts.get(torch_model, []):
                if pno not in seen and pno in ds.parts:
                    seen.add(pno); found.append(ds.parts[pno])

            torch_dict = ds.torches.get(torch_model) or {}
            if not torch_dict:
                for k, v in ds.torches.items():
                    if k.upper() == torch_model.upper():
                        torch_dict = v; break

            eco = (torch_dict.get('ecosystem') or '').upper()
            cc  = (torch_dict.get('current_class') or '').upper()
            if eco and cc:
                for cs in ds._consumable_sets:
                    if (cs.get('ecosystem','').upper() == eco and
                            cs.get('torch_current_class','').upper() == cc):
                        for item in cs.get('items', []):
                            pid = item.get('part_id','')
                            if pid and pid not in seen and pid in ds.parts:
                                seen.add(pid); found.append(ds.parts[pid])

        if not found and fuzzy:
            eco = (getattr(fuzzy,'ecosystem_hint','') or '').upper()
            cc  = (getattr(fuzzy,'current_class_hint','') or '').upper()
            if eco and cc:
                for cs in ds._consumable_sets:
                    if (cs.get('ecosystem','').upper() == eco and
                            cs.get('torch_current_class','').upper() == cc):
                        for item in cs.get('items', []):
                            pid = item.get('part_id','')
                            if pid and pid not in seen and pid in ds.parts:
                                seen.add(pid); found.append(ds.parts[pid])

        return found[:top_k]

    def _stage_upsell(self, query, fuzzy, top_k):
        """Stage Upsell: part_no + companion keywords → anchor + compat edges."""
        upsell_kw = ('cần','thêm','đi kèm','đi với','dùng chung','dùng với',
                     'kèm','lấy thêm','cần gì','cần béc','cần chụp')
        if not any(kw in query.lower() for kw in upsell_kw):
            return []

        import re as _re
        ds = self.ds
        found: List[dict] = []
        seen: set = set()

        anchors: List[str] = []
        if fuzzy:
            for pno, sim in (fuzzy.part_no_candidates or []):
                if sim >= 0.80: anchors.append(pno)
            for mc, sim in (fuzzy.model_code_candidates or []):
                if sim >= 0.75:
                    for alias_dict in (getattr(ds,'p_alias',{}), getattr(ds,'d_alias',{})):
                        tokin = alias_dict.get(mc.upper())
                        if tokin: anchors.append(tokin); break

        tokens = _re.findall(r'\b\d{6}\b', query)
        anchors.extend(tokens)

        for anchor in anchors[:2]:
            if anchor in ds.parts and anchor not in seen:
                seen.add(anchor); found.append(ds.parts[anchor])
            for edge in ds._compat_edges:
                rel = edge.get('relation_type','')
                if rel not in ('compatible_with','assembled_with','functional_requires'):
                    continue
                comp = None
                if edge.get('from_part') == anchor: comp = edge.get('to_part')
                elif edge.get('to_part') == anchor: comp = edge.get('from_part')
                if comp and comp not in seen and comp in ds.parts:
                    seen.add(comp); found.append(ds.parts[comp])

        return found[:top_k]

    def _stage_comparison(self, query, fuzzy, top_k):
        """Stage Compare: wire_size/amp comparison → search each side."""
        import re as _re
        comp_kw = ('khác gì','so sánh','tốt hơn','bền hơn',' vs ','phân biệt','khác nhau')
        if not any(kw in query.lower() for kw in comp_kw):
            return []

        ds = self.ds
        found: List[dict] = []
        seen: set = set()

        wire_matches = _re.findall(r'(\d+\.?\d*)\s*(?:mm|ly)', query.lower())
        wire_sizes = []
        for w in wire_matches:
            try: wire_sizes.append(float(w))
            except ValueError: pass

        eco = (getattr(fuzzy,'ecosystem_hint',None) if fuzzy else None) or 'N'
        cc  = (getattr(fuzzy,'current_class_hint',None) if fuzzy else None)

        for wire in wire_sizes[:2]:
            entities = {'_raw_query': query, 'wire_size': wire, 'ecosystem': eco}
            if cc: entities['current_class'] = cc
            try:
                r = ds._search_by_desc(entities)
                if r.get('success'):
                    for p in (r.get('data') or [])[:3]:
                        pno = p.get('tokin_part_no','')
                        if pno and pno not in seen:
                            seen.add(pno); found.append(p)
            except Exception: pass

        return found[:top_k]

    def _stage_faiss(
        self,
        query:         str,
        ecosystem:     Optional[str],
        current_class: Optional[str],
        category:      Optional[str],
        top_k:         int,
    ) -> List[dict]:
        """Stage FAISS: semantic vector search với post-filter."""
        if not query or not query.strip():
            return []
        try:
            from core.vector_index import VectorIndex
            vi = VectorIndex(auto_build=False)
            if vi._index is None:
                return []
        except Exception as e:
            log.debug(f"[RetrievalOrch] VectorIndex unavailable: {e}")
            return []
        ds = self.ds
        try:
            raw = vi.search(query, top_k=top_k * 3)
        except Exception as e:
            log.debug(f"[RetrievalOrch] FAISS search error: {e}")
            return []
        results = []
        seen: set = set()
        for item in (raw or []):
            pno = (item.get('tokin_part_no', '') if isinstance(item, dict)
                   else getattr(item, 'tokin_part_no', ''))
            if not pno or pno in seen:
                continue
            part = ds.parts.get(pno)
            if not part:
                continue
            if ecosystem and part.get('ecosystem', '').upper() != ecosystem.upper():
                continue
            if current_class:
                cc = part.get('current_class', '')
                if current_class.upper() not in cc.upper():
                    continue
            if category and part.get('category', '').lower() != category.lower():
                continue
            seen.add(pno)
            results.append(part)
            if len(results) >= top_k:
                break
        log.info(f"[RetrievalOrch] _stage_faiss: {len(results)} parts query={query!r:.40}")
        return results

    def _wire_size_matches(self, part: dict, wire_size_mm: float, tol: float = 0.05) -> bool:
        """Fix: check wire_size cho cả float lẫn wire_size_range dict/str."""
        ws = part.get('wire_size_mm')
        if ws is not None:
            try:
                return abs(float(ws) - wire_size_mm) <= tol
            except (TypeError, ValueError):
                pass
        wsr = part.get('wire_size_range')
        if isinstance(wsr, dict):
            mn, mx = wsr.get('min'), wsr.get('max')
            if mn is not None and mx is not None:
                try:
                    return float(mn) - tol <= wire_size_mm <= float(mx) + tol
                except (TypeError, ValueError):
                    pass
        elif isinstance(wsr, str):
            import re as _re
            nums = _re.findall(r'\d+\.\d+', wsr)
            if len(nums) >= 2:
                try:
                    return float(nums[0]) - tol <= wire_size_mm <= float(nums[-1]) + tol
                except ValueError:
                    pass
            elif len(nums) == 1:
                try:
                    return abs(float(nums[0]) - wire_size_mm) <= tol
                except ValueError:
                    pass
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Singleton + convenience
# ══════════════════════════════════════════════════════════════════════════════

_instance: Optional[RetrievalOrchestrator] = None

def get_retrieval_orchestrator(ds=None) -> RetrievalOrchestrator:
    """Lazy singleton."""
    global _instance
    if _instance is None:
        _instance = RetrievalOrchestrator(ds=ds)
    return _instance


def retrieve(
    query:         str,
    ecosystem:     Optional[str]   = None,
    current_class: Optional[str]   = None,
    wire_size_mm:  Optional[float] = None,
    category:      Optional[str]   = None,
    top_k:         int             = 15,
) -> RetrievalResult:
    """Shortcut: retrieve(query, ...) → RetrievalResult."""
    return get_retrieval_orchestrator().retrieve(
        query=query,
        ecosystem=ecosystem,
        current_class=current_class,
        wire_size_mm=wire_size_mm,
        category=category,
        top_k=top_k,
    )
