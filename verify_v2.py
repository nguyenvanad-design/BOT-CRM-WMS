import ast, sys, json, re

all_ok = True

py_checks = {
    "core/llm_orchestrator_v2.py": {
        "must_have": [
            "def build_tool_summary",
            "def _build_context_hint",
            "[REST] AUTO-INJECT",
            "[Planner] AUTO-INJECT",
            "_detect_category_from_query",
            "_CATEGORY_KEYWORDS",
            "include_categories",
            "PAGINATION-INJECT",
            "_pagination_kw",
            "_is_pagination",
            "_prev_pno",
            "has_more=false",
            # v2 pagination category-lock additions
            "_CAT_KEYWORD_MAP",
            "_last_assistant_text",
            "_detected_cats",
            "Category lock from prev assistant",
            "_last_upsell_pno",
            "_last_upsell_page",
            "_last_upsell_cats",
            "PAGINATION PRE-INJECT",
            "PRE-INJECT PAGINATION",
            "ORDER FLOW",
            "order_manager",
            "detect_order_trigger",
            "finalize_order",
        ],
        "must_not": [")[:6000]", "_summary_limit"],
    },
    "core/system_prompts.py": {
        "must_have": [
            "ASSISTANT_PROMPT", "TOOL_SCHEMA",
            "[13]", "[14]", "[15]", "[16]", "[17]",
            "[18]",
            "Pagination TRONG CÙNG CATEGORY",
            "include_categories", "MULTI-TOOL",
            "FLOW CH\u1ed0T \u0110\u01a0N",
            "ORDER-1", "ORDER-2", "ORDER-3",
            "0909 484 159",
        ],
        "must_not": [],
    },
    "core/tool_wrappers.py": {
        "must_have": [
            "include_categories", "editorial_picks",
            "PRIORITY FALLBACK 1", "ds.parts.get(canonical)",
            "result_companions", "PAGE_SIZE", "has_more",
            "_part_to_response(ep_raw)",
            # top-up additions
            "filtered_companions",
            "len(filtered_companions) <",
        ],
        "must_not": [],
    },
}

for path, cfg in py_checks.items():
    try:
        content = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        print("FILE NOT FOUND: " + path)
        all_ok = False
        continue
    try:
        ast.parse(content)
        syntax = "OK"
    except SyntaxError as e:
        syntax = "ERROR " + str(e)
        all_ok = False
    print("\n" + path + " | syntax=" + syntax + " | lines=" + str(len(content.splitlines())))
    for c in cfg["must_have"]:
        found = c in content
        if not found: all_ok = False
        print("  [" + ("OK" if found else "MISSING") + "] " + c)
    for c in cfg["must_not"]:
        found = c in content
        if found: all_ok = False
        print("  [" + ("STILL_EXISTS" if found else "REMOVED") + "] BAD: " + c)

# Extra check: _already_upsell assignments
orch = open("core/llm_orchestrator_v2.py", encoding="utf-8").read()
count_already = len(re.findall(r'_already_upsell\s*=', orch))
ok_already = count_already == 2
if not ok_already: all_ok = False
print("\n  [" + ("OK" if ok_already else "ISSUE") + "] _already_upsell assignments: " + str(count_already) + " (expected 2)")

# Check order_manager.py
print("\ncore/order_manager.py")
try:
    import ast as _ast2
    om = open("core/order_manager.py", encoding="utf-8").read()
    _ast2.parse(om)
    print("  syntax=OK | lines=" + str(len(om.splitlines())))
    for c in ["class OrderState","detect_order_trigger","parse_order_from_query",
              "process_slot_answer","finalize_order","AUTOSS_INFO",
              "0909 484 159","info@autoss.vn","orders.jsonl","SLOT_QUESTIONS"]:
        found = c in om
        if not found: all_ok = False
        print("  [" + ("OK" if found else "MISSING") + "] " + c)
except FileNotFoundError:
    print("  FILE NOT FOUND"); all_ok = False
except Exception as e:
    print("  ERROR: " + str(e)); all_ok = False

print("\nmain.py (orders endpoint)")
try:
    ms = open("main.py", encoding="utf-8").read()
    for c in ["/orders", "router_orders"]:
        found = c in ms
        if not found: all_ok = False
        print("  [" + ("OK" if found else "MISSING") + "] " + c)
except FileNotFoundError:
    print("  FILE NOT FOUND"); all_ok = False

print("\ndata/tokinarc_data_v19.json")
try:
    data    = json.load(open("data/tokinarc_data_v19.json", encoding="utf-8"))
    parts   = data.get("parts", [])
    torches = data.get("torches", [])
    cs      = data.get("consumable_sets", [])
    edges   = data.get("compatibility_edges", [])
    part_map = {p.get("tokin_part_no"): p for p in parts}

    ta            = [t for t in torches if t.get("model_code","").startswith("TA")]
    ta_with_picks = [t for t in ta if t.get("editorial_picks")]
    tig_cs_ok     = [s for s in cs if "TIG" in s.get("set_id","") and s.get("torch_models") and s.get("parts")]
    p001002       = next((x for x in parts if x.get("tokin_part_no") == "001002"), None)
    p002001       = next((x for x in parts if x.get("tokin_part_no") == "002001"), None)
    picks_001002  = p001002.get("editorial_picks", []) if p001002 else []
    picks_002001  = p002001.get("editorial_picks", []) if p002001 else []
    edges_001002  = len([e for e in edges if e.get("from") == "001002"])

    # Nozzle picks count for 002001
    nozzle_picks_002001 = [x for x in picks_002001
                           if part_map.get(x, {}).get("category") == "Nozzle"]

    # Tips missing valid Nozzle picks
    tips_missing_nozzle = [
        p.get("tokin_part_no") for p in parts
        if p.get("category") == "Tip" and
        not [x for x in p.get("editorial_picks", [])
             if part_map.get(x, {}).get("category") == "Nozzle"
             and part_map.get(x, {}).get("ecosystem") not in ("WX",)]
    ]
    p002004       = next((x for x in parts if x.get("tokin_part_no") == "002004"), None)
    picks_002004  = p002004.get("editorial_picks", []) if p002004 else []
    nozzle_picks_002004 = [x for x in picks_002004
                           if part_map.get(x, {}).get("category") == "Nozzle"
                           and part_map.get(x, {}).get("ecosystem") not in ("WX",)]

    for ok, label in [
        (len(ta_with_picks) == len(ta),   "TA torches with editorial_picks: " + str(len(ta_with_picks)) + "/" + str(len(ta))),
        (len(tig_cs_ok) >= 5,             "TIG consumable_sets with parts: " + str(len(tig_cs_ok))),
        ("036001" in picks_001002,        "001002 picks has 036001"),
        ("036001" in picks_002001,        "002001 picks has 036001"),
        (edges_001002 >= 10,              "compatibility_edges from 001002: " + str(edges_001002)),
        # nozzle picks checks
        (len(nozzle_picks_002001) >= 3,   "002001 Nozzle picks >= 3: " + str(len(nozzle_picks_002001)) + " → " + str(nozzle_picks_002001)),
        ("001002" in nozzle_picks_002001, "002001 Nozzle picks includes 001002 (primary)"),
        ("001003" in nozzle_picks_002001, "002001 Nozzle picks includes 001003"),
        (len(nozzle_picks_002004) >= 1,   "002004 Nozzle picks >= 1 (non-WX): " + str(nozzle_picks_002004)),
        (len(tips_missing_nozzle) == 0,   "All Tips have valid Nozzle picks (missing: " + str(tips_missing_nozzle) + ")"),
    ]:
        if not ok: all_ok = False
        print("  [" + ("OK" if ok else "MISSING") + "] " + label)
except Exception as e:
    print("  ERROR: " + str(e))
    all_ok = False

print("")
print("RESULT: " + ("ALL PASS" if all_ok else "HAS ISSUES"))
