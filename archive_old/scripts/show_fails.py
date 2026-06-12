import json, sys

fname = sys.argv[1] if len(sys.argv) > 1 else "results_v6_r2.json"
data  = json.load(open(fname, encoding="utf-8"))
fails = [c for c in data["results"] if not c.get("passed")]
fails.sort(key=lambda x: x.get("group", ""))

print(f"Total fails: {len(fails)}\n")
print(f"{'Group':12} {'ID':5} {'Got Intent':20} {'Fail Reason':45} Query")
print("-" * 110)
for c in fails:
    print(
        f"{c.get('group','?'):12} "
        f"#{c.get('case_id','?'):4} "
        f"{c.get('actual_intent','?'):20} "
        f"{(c.get('fail_reason') or '')[:45]:45} "
        f"{(c.get('query') or '')[:50]}"
    )
