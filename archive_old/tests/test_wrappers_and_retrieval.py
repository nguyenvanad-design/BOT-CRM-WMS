#!/usr/bin/env python3
# test_wrappers_and_retrieval.py
# Smoke test cho tool_wrappers.py và retrieval_orchestrator.py
# Dùng Mock DataStore — không cần tokinarc_data_v14.json
# Run: python test_wrappers_and_retrieval.py
# UTF-8 NO BOM

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
results = []

def check(label: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append(condition)
    msg = f"  {status} {label}"
    if detail and not condition:
        msg += f"  ← {detail}"
    print(msg)

def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")

# ─── Minimal Mock DataStore ───────────────────────────────────────────────────

class MockDS:
    """Minimal mock giống TokinarcDataStore interface."""
    def __init__(self):
        self.parts = {
            "002003": {
                "tokin_part_no": "002003", "display_name_vi": "Béc hàn N 1.2mm x 45L",
                "category": "Tip", "ecosystem": "N", "current_class": "350A",
                "wire_size_mm": 1.2, "business": {"price_vnd": 20000, "price_unit": "cái"},
                "p_part_nos": ["TET00083"], "d_part_nos": [],
            },
            "002001": {
                "tokin_part_no": "002001", "display_name_vi": "Béc hàn N 0.9mm x 45L",
                "category": "Tip", "ecosystem": "N", "current_class": "350A",
                "wire_size_mm": 0.9, "business": {"price_vnd": 18000, "price_unit": "cái"},
            },
            "001002": {
                "tokin_part_no": "001002", "display_name_vi": "Chụp khí N 350A ∅16mm",
                "category": "Nozzle", "ecosystem": "N", "current_class": "350A",
                "business": {"price_vnd": 65000, "price_unit": "cái"},
            },
            "023009": {
                "tokin_part_no": "023009", "display_name_vi": "Béc hàn D 1.0mm",
                "category": "Tip", "ecosystem": "D", "current_class": "350A",
                "wire_size_mm": 1.0, "business": {"price_vnd": 22000, "price_unit": "cái"},
            },
            "046301": {
                "tokin_part_no": "046301", "display_name_vi": "TKS-RC Nozzle Cleaner",
                "category": "Tool", "ecosystem": "UNIVERSAL", "current_class": "ALL",
                "business": {"is_contact_price": True},
            },
        }
        self.torches = {
            "TK-308RR": {
                "model_code": "TK-308RR", "ecosystem": "N", "current_class": "350A",
                "wire_size": "0.9-1.6mm", "cooling": "Air",
                "business": {"is_contact_price": True},
            },
            "D-350R": {
                "model_code": "D-350R", "ecosystem": "D", "current_class": "350A",
                "business": {"is_contact_price": True},
            },
        }
        self.p_alias = {"TET00083": "002003"}
        self.d_alias = {"K232B22": "002003"}
        self.o_part_alias = {}
        self.p_model_alias = {}
        self.d_model_alias = {}
        self.o_model_alias = {}
        self.model_alias = {"TKS-RC": "046301", "WF-120": "046301"}
        self.compat = {"002003": {"001002"}, "001002": {"002003"}}
        self.compat_conf = {("002003","001002"): 1.0, ("001002","002003"): 1.0}
        self.neg_rules = {("N","D"): [{"incompatibility_reason":"Khác hệ","rule_id":"N_D"}]}
        self.neg_part_rules = {}
        self._torch_exceptions = {}
        self.torch_parts = {
            "TK-308RR": ["002003","002001","001002"],
            "D-350R":   ["023009"],
        }
        self.by_category = {
            "Tip": ["002003","002001","023009"],
            "Nozzle": ["001002"],
            "Tool": ["046301"],
        }
        self.cat_vocab = {
            "tip": "Tip", "bec": "Tip", "nozzle": "Nozzle", "chup": "Nozzle",
            "insulator": "Insulator", "cach dien": "Insulator",
        }
        self.by_eco_cc = {
            ("N","350A"): ["002003","002001","001002"],
            ("D","350A"): ["023009"],
        }
        self.symptom_map = {
            "ts_excessive_spatter": {
                "symptom": "Bắn tóe nhiều",
                "likely_causes": ["Chụp khí mòn","Béc hàn mòn"],
                "recommended_action": "Thay chụp khí. Kiểm tra béc.",
            }
        }
        self.rep_procedures = {}
        self.asm_sequences = {}
        self._negative_rules = [
            {"rule_id":"N_D","from_ecosystem":"N","to_ecosystem":"D",
             "from_category":"","to_category":"","incompatibility_reason":"Khác hệ",
             "exception_torch_models":[],"confidence":1.0},
        ]
        self._consumable_sets = [
            {
                "set_id": "N350A_standard",
                "ecosystem": "N",
                "torch_current_class": "350A",
                "default_wire_size_mm": 1.2,
                "items": [
                    {"part_id":"002003","part_role":"Tip","is_mandatory":True,"priority_rank":1,"default_quantity":10},
                    {"part_id":"001002","part_role":"Nozzle","is_mandatory":True,"priority_rank":2,"default_quantity":2},
                ],
            }
        ]
        self._tpms = [
            {"torch_model":"TK-308RR","part_nos":["002003","002001"],"part_role":"Tip","is_mandatory":True},
            {"torch_model":"TK-308RR","part_nos":["001002"],"part_role":"Nozzle","is_mandatory":True},
        ]
        self._assembly = {}
        self._parts_list = list(self.parts.values())

    def query(self, intent: str, e: dict) -> dict:
        """Simplified query handler cho test."""
        if intent == "LOOKUP":
            for pno in (e.get("part_nos") or []):
                if pno in self.parts:
                    return {"success":True,"data":self.parts[pno],"reason":""}
            for pno in (e.get("p_part_nos") or []):
                tokin = self.p_alias.get(pno.upper())
                if tokin:
                    return {"success":True,"data":{**self.parts[tokin],
                            "_resolved_from":pno,"_brand":"Panasonic"},"reason":""}
            for pno in (e.get("d_part_nos") or []):
                tokin = self.d_alias.get(pno.upper())
                if tokin:
                    return {"success":True,"data":{**self.parts[tokin],
                            "_resolved_from":pno,"_brand":"Daihen/OTC"},"reason":""}
            for tm in (e.get("torch_models") or []):
                if tm in self.torches:
                    return {"success":True,"data":{"_type":"torch",**self.torches[tm]},"reason":""}
            raw = (e.get("_raw_query","")).upper()
            for alias, pno in self.model_alias.items():
                if alias in raw and pno in self.parts:
                    return {"success":True,"data":self.parts[pno],"reason":""}
            return {"success":False,"data":None,"reason":"NO_MATCH"}

        if intent == "SEARCH_BY_DESC":
            eco  = (e.get("ecosystem") or "").upper()
            cc   = (e.get("current_class") or "").upper()
            ws   =  e.get("wire_size")
            cats =  e.get("categories") or []
            cat  = cats[0] if cats else ""
            res  = []
            for p in self.parts.values():
                if eco and (p.get("ecosystem") or "").upper() not in (eco,"UNIVERSAL"):
                    continue
                if cc and (p.get("current_class") or "").upper() != cc:
                    continue
                if ws:
                    pw = p.get("wire_size_mm")
                    if pw is None or abs(float(pw)-ws) > 0.05:
                        continue
                if cat and cat.lower() not in (p.get("category") or "").lower():
                    continue
                res.append(p)
            return ({"success":True,"data":res,"reason":""} if res
                    else {"success":False,"data":None,"reason":"NO_RESULTS"})

        if intent == "REPLACEMENT":
            for pno in (e.get("p_part_nos") or []):
                tokin = self.p_alias.get(pno.upper())
                if tokin:
                    return {"success":True,"data":{"source_code":pno,
                            "source_brand":"Panasonic","tokin_part_no":tokin,
                            "part_info":self.parts[tokin]},"reason":""}
            for pno in (e.get("d_part_nos") or []):
                tokin = self.d_alias.get(pno.upper())
                if tokin:
                    return {"success":True,"data":{"source_code":pno,
                            "source_brand":"Daihen/OTC","tokin_part_no":tokin,
                            "part_info":self.parts[tokin]},"reason":""}
            return {"success":False,"data":None,"reason":"NO_REPLACEMENT_FOUND"}

        if intent == "COMPATIBILITY_CHECK":
            pnos = e.get("part_nos") or []
            if len(pnos) >= 2:
                pa, pb = pnos[0], pnos[1]
                compat = pb in self.compat.get(pa, set())
                return {"success":True,"data":{
                    "part_a":{"part_no":pa},"part_b":{"part_no":pb},
                    "compatible":compat,
                    "reason":"direct" if compat else "no edge",
                },"reason":""}
            return {"success":False,"data":None,"reason":"INSUFFICIENT_ENTITIES"}

        if intent == "CONSUMABLE_SET":
            eco = (e.get("ecosystem") or "").upper()
            cc  = (e.get("current_class") or "").upper()
            for cs in self._consumable_sets:
                if cs["ecosystem"].upper()==eco and cs["torch_current_class"].upper()==cc:
                    enriched = []
                    for item in cs["items"]:
                        pid = item["part_id"]
                        enriched.append({**item,
                            "display_name_vi": self.parts.get(pid,{}).get("display_name_vi",""),
                            "ecosystem": self.parts.get(pid,{}).get("ecosystem",""),
                        })
                    return {"success":True,"data":{**cs,"items":enriched},"reason":""}
            return {"success":False,"data":None,"reason":"NO_CONSUMABLE_SET_FOUND"}

        if intent == "UPSELL":
            owned = set(e.get("owned_parts") or e.get("part_nos") or [])
            eco   = (e.get("ecosystem") or "N").upper()
            cc    = (e.get("current_class") or "350A").upper()
            cs_r  = self.query("CONSUMABLE_SET", {"ecosystem":eco,"current_class":cc})
            if not cs_r["success"]:
                return {"success":False,"data":None,"reason":"CANNOT_DETERMINE_TARGET_SET"}
            cs   = cs_r["data"]
            missing = [{"part_id":i["part_id"],"display_name_vi":i["display_name_vi"],
                        "part_role":i["part_role"],"is_mandatory":i["is_mandatory"],
                        "business":self.parts.get(i["part_id"],{}).get("business",{}),
                        "ecosystem":eco}
                       for i in cs["items"] if i["part_id"] not in owned]
            return {"success":True,"data":{"owned":list(owned),"missing":missing,
                    "ecosystem":eco,"current_class":cc,"set_id":cs["set_id"]},"reason":""}

        if intent == "REPAIR":
            raw = (e.get("_raw_query") or "").lower()
            ts  = None
            for kw, ts_id in [("ban toe","ts_excessive_spatter"),("bắn tóe","ts_excessive_spatter")]:
                if kw in raw and ts_id in self.symptom_map:
                    ts = self.symptom_map[ts_id]
                    break
            adapted = None
            if ts:
                adapted = {"symptom_vi":ts["symptom"],"causes":ts["likely_causes"],
                           "actions":[a.strip() for a in ts["recommended_action"].split(".") if a.strip()]}
            return {"success":True,"data":{"troubleshooting":adapted,"related_parts":[]},"reason":""}

        if intent == "AGGREGATE":
            raw  = (e.get("_raw_query") or "").lower()
            eco  = (e.get("ecosystem") or "").upper()
            if "sung" in raw or "torch" in raw or "súng" in raw:
                tlist = list(self.torches.values())
                if eco:
                    tlist = [t for t in tlist if (t.get("ecosystem") or "").upper()==eco]
                return {"success":True,"data":{"type":"torch_list","count":len(tlist),"torches":tlist},"reason":""}
            return {"success":True,"data":{"total_parts":len(self.parts)},"reason":""}

        if intent in ("OUT_OF_SCOPE","CLARIFY"):
            return {"success":False,"data":None,"reason":intent}

        return {"success":False,"data":None,"reason":f"UNKNOWN:{intent}"}

    def _text_search_fallback(self, query, eco="", cc="", ws=None, cat="", top_k=10):
        """Simple token match fallback."""
        q = query.lower()
        results = []
        for p in self.parts.values():
            text = " ".join(filter(None,[
                (p.get("display_name_vi") or "").lower(),
                p.get("tokin_part_no",""),
                (p.get("category") or "").lower(),
                (p.get("ecosystem") or "").lower(),
            ]))
            tokens = [t for t in q.split() if len(t) >= 3]
            score  = sum(1 for t in tokens if t in text)
            if score >= 1:
                results.append((score, p))
        results.sort(key=lambda x: -x[0])
        return [p for _,p in results[:top_k]]


# ─── Inject mock DS vào modules ───────────────────────────────────────────────

_mock_ds = MockDS()

# Override singletons
import tool_wrappers
tool_wrappers.set_data_store(_mock_ds)

import retrieval_orchestrator
retrieval_orchestrator._instance = None  # reset

from retrieval_orchestrator import RetrievalOrchestrator
_ret = RetrievalOrchestrator(ds=_mock_ds)


# ══════════════════════════════════════════════════════════════════════════════
# TOOL WRAPPERS TESTS
# ══════════════════════════════════════════════════════════════════════════════

section("tool_wrappers — lookup_part (tokin code)")
r = tool_wrappers.dispatch("lookup_part", {"part_no": "002003"})
check("success",              r["success"])
check("data has tokin_part_no", r.get("data",{}).get("tokin_part_no") == "002003")
check("_in_torches populated",  "_in_torches" in r.get("data",{}))

section("tool_wrappers — lookup_part (Panasonic alias)")
r = tool_wrappers.dispatch("lookup_part", {"part_no": "TET00083"})
check("success",              r["success"])
check("_resolved_from=TET00083", r.get("data",{}).get("_resolved_from") == "TET00083")
check("_brand=Panasonic",     r.get("data",{}).get("_brand") == "Panasonic")

section("tool_wrappers — lookup_part (model alias TKS-RC)")
r = tool_wrappers.dispatch("lookup_part", {"part_no": "TKS-RC"})
check("success",              r["success"])
check("part_no=046301",       r.get("data",{}).get("tokin_part_no") == "046301")

section("tool_wrappers — lookup_part (torch model)")
r = tool_wrappers.dispatch("lookup_part", {"torch_model": "TK-308RR"})
check("success",              r["success"])
check("_type=torch",          r.get("data",{}).get("_type") == "torch",
      f"data={r.get('data')}")

section("tool_wrappers — lookup_part (not found)")
r = tool_wrappers.dispatch("lookup_part", {"part_no": "999999"})
check("success=False",        not r["success"])
check("reason=NO_MATCH",      "NO_MATCH" in r.get("reason",""))

section("tool_wrappers — search_parts")
r = tool_wrappers.dispatch("search_parts", {
    "ecosystem": "N", "current_class": "350A", "category": "Tip"})
check("success",              r["success"])
check("≥1 Tip parts",         len(r.get("data",[]) or []) >= 1)
check("all eco=N",            all(p.get("ecosystem")=="N" for p in (r.get("data") or [])))

section("tool_wrappers — search_parts (wire_size filter)")
r = tool_wrappers.dispatch("search_parts", {
    "ecosystem": "N", "wire_size": 1.2})
check("success",              r["success"])
check("wire_size=1.2",        all(abs((p.get("wire_size_mm") or 0)-1.2) < 0.05
                               for p in (r.get("data") or [])))

section("tool_wrappers — get_consumable_set")
r = tool_wrappers.dispatch("get_consumable_set", {
    "ecosystem": "N", "current_class": "350A"})
check("success",              r["success"])
check("has items",            len((r.get("data") or {}).get("items",[]) or []) > 0)
check("set_id=N350A_standard",(r.get("data") or {}).get("set_id") == "N350A_standard")

section("tool_wrappers — find_upsell_companions")
r = tool_wrappers.dispatch("find_upsell_companions", {
    "owned_parts": ["002003"], "ecosystem": "N", "current_class": "350A"})
check("success",              r["success"])
check("missing has items",    len((r.get("data") or {}).get("missing",[]) or []) >= 1)
check("002003 not in missing",
      "002003" not in [(m.get("part_id") or "") 
                       for m in (r.get("data") or {}).get("missing",[])])

section("tool_wrappers — find_replacement (Panasonic)")
r = tool_wrappers.dispatch("find_replacement", {"source_part_no": "TET00083"})
check("success",              r["success"])
check("tokin=002003",         (r.get("data") or {}).get("tokin_part_no") == "002003")
check("source_brand=Panasonic",(r.get("data") or {}).get("source_brand") == "Panasonic")

section("tool_wrappers — check_compatibility (compatible)")
r = tool_wrappers.dispatch("check_compatibility", {"part_a": "002003", "part_b": "001002"})
check("success",              r["success"])
check("compatible=True",      (r.get("data") or {}).get("compatible") == True)

section("tool_wrappers — get_torches")
r = tool_wrappers.dispatch("get_torches", {"ecosystem": "N"})
check("success",              r["success"])
check("has torches",          len((r.get("data") or {}).get("torches",[]) or []) >= 1)

section("tool_wrappers — get_troubleshoot")
r = tool_wrappers.dispatch("get_troubleshoot", {"symptom": "bắn tóe"})
check("success",              r["success"])
check("troubleshooting not None",
      (r.get("data") or {}).get("troubleshooting") is not None)
check("causes list",          len((r.get("data") or {}).get("troubleshooting",{}).get("causes",[]) or []) > 0)

section("tool_wrappers — unknown tool")
r = tool_wrappers.dispatch("nonexistent_tool", {})
check("success=False",        not r["success"])
check("reason=UNKNOWN_TOOL",  "UNKNOWN_TOOL" in r.get("reason",""))

section("tool_wrappers — missing args")
r = tool_wrappers.dispatch("lookup_part", {})
check("success=False",        not r["success"])
check("reason=MISSING",       "MISSING" in r.get("reason",""))

# ══════════════════════════════════════════════════════════════════════════════
# RETRIEVAL ORCHESTRATOR TESTS
# ══════════════════════════════════════════════════════════════════════════════

section("retrieval — exact: 6-digit tokin part_no")
r = _ret.retrieve("002003 giá bao nhiêu")
check("success",              r.success)
check("match_type=exact_tokin", r.match_type == "exact_tokin",
      f"match_type={r.match_type}")
check("matched_part_no=002003", r.matched_part_no == "002003")
check("ecosystem=N",          r.ecosystem == "N")
check("wire_size=1.2",        r.wire_size == 1.2)

section("retrieval — exact: Panasonic alias TET00083")
r = _ret.retrieve("TET00083 tương đương Tokin gì")
check("success",              r.success)
check("match_type=exact_alias_p", r.match_type == "exact_alias_p",
      f"match_type={r.match_type}")
check("_brand=Panasonic",     (r.parts[0] if r.parts else {}).get("_brand") == "Panasonic")
check("matched_part_no=002003", r.matched_part_no == "002003")

section("retrieval — exact: Daihen alias K232B22")
r = _ret.retrieve("K232B22 có không")
check("success",              r.success)
check("match_type=exact_alias_d", r.match_type == "exact_alias_d",
      f"match_type={r.match_type}")

section("retrieval — exact: model alias TKS-RC")
r = _ret.retrieve("TKS-RC giá bao nhiêu")
check("success",              r.success)
check("match_type=exact_model_alias", r.match_type == "exact_model_alias",
      f"match_type={r.match_type}")

section("retrieval — exact: torch model TK-308RR")
r = _ret.retrieve("TK-308RR thông số")
check("success",              r.success)
check("match_type=exact_torch", r.match_type == "exact_torch",
      f"match_type={r.match_type}")
check("has torches",          len(r.torches) > 0)

section("retrieval — exact: torch no-hyphen TK308RR")
r = _ret.retrieve("TK308RR thông số")
check("success",              r.success)
check("match_type exact_torch or fuzzy_torch",
      r.match_type in ("exact_torch","fuzzy_torch"),
      f"match_type={r.match_type}")

section("retrieval — structured: eco+cc+cat")
r = _ret.retrieve("béc N 350A", session_eco=None)
check("success",              r.success)
check("match_type=structured or text_fallback",
      r.match_type in ("structured","text_fallback","exact_tokin","exact_alias_p"),
      f"match_type={r.match_type}")
check("parts not empty",      len(r.parts) > 0)

section("retrieval — structured: wire_size filter 1.2mm hệ N")
r = _ret.retrieve("béc 1.2mm hệ N")
check("success",              r.success)
check("parts not empty",      len(r.parts) > 0)

section("retrieval — text fallback: no code no eco")
r = _ret.retrieve("chụp khí 350")
check("success or failure graceful", isinstance(r.success, bool))
check("has ds_result",        r.ds_result is not None)

section("retrieval — empty query")
r = _ret.retrieve("")
check("success=False",        not r.success)
check("reason=EMPTY_QUERY",   r.reason == "EMPTY_QUERY")

section("retrieval — retrieve_for_intent LOOKUP")
r = _ret.retrieve_for_intent("LOOKUP", {"part_nos":["002001"],"_raw_query":"002001"})
check("success",              r.success)
check("match_type exact",     "exact" in r.match_type)

section("retrieval — retrieve_for_intent SEARCH_BY_DESC")
r = _ret.retrieve_for_intent("SEARCH_BY_DESC", {
    "ecosystem":"D","current_class":"350A","_raw_query":"béc D 350"})
check("success",              r.success)
check("match_type structured/fallback",
      r.match_type in ("structured","text_fallback"),
      f"match_type={r.match_type}")

section("retrieval — retrieve_for_intent CONSUMABLE_SET (not retrieval)")
r = _ret.retrieve_for_intent("CONSUMABLE_SET", {"ecosystem":"N","current_class":"350A"})
check("success=False (not retrieval intent)", not r.success)
check("reason INTENT_NOT_RETRIEVAL", "INTENT_NOT_RETRIEVAL" in r.reason)

# ─── Summary ──────────────────────────────────────────────────────────────────

print(f"\n{'═'*60}")
passed = sum(results)
total  = len(results)
pct    = passed / total * 100 if total else 0
status = "\033[92mPASS\033[0m" if passed == total else "\033[91mFAIL\033[0m"
print(f"  {status}  {passed}/{total} ({pct:.0f}%)")
print(f"{'═'*60}\n")
if passed < total:
    sys.exit(1)
