# run_eval.py — TokinArc eval script
# Chạy: python run_eval.py
# FIX (security 2026-06): bỏ hardcode URL public + API key dev.
#   set TOKINARC_EVAL_URL / TOKINARC_API_KEY trước khi chạy (hoặc dùng .env).
import os
import requests
import json
import time
from collections import Counter

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

with open('eval_700.json', encoding='utf-8') as f:
    cases = json.load(f)

URL = os.getenv('TOKINARC_EVAL_URL', 'http://localhost:8080/api/v2/query')
_KEY = os.getenv('TOKINARC_API_KEY', '')
if not _KEY:
    raise SystemExit('TOKINARC_API_KEY chưa được set (env hoặc .env) — không chạy eval.')
H   = {'X-API-Key': _KEY, 'Content-Type': 'application/json'}

results = Counter()
fails   = []
errors  = []

print(f"Starting eval — {len(cases)} queries")
print("-" * 55)

for i, c in enumerate(cases, 1):
    intent = c.get('intent', '')
    exp    = c.get('expected_part_nos', [])

    if intent == 'OUT_OF_SCOPE' and not exp:
        results['OOS_PASS'] += 1
        continue
    if not exp:
        results['SKIP'] += 1
        continue

    try:
        r    = requests.post(URL, headers=H,
                             json={'query': c['query']},
                             timeout=90)
        resp = r.json()
        text = (resp.get('text') or '').upper()

        hit = any(p.upper() in text for p in exp)
        if hit:
            results['PASS'] += 1
        else:
            results['FAIL'] += 1
            if len(fails) < 500:
                # Root cause detection
                cause = 'unknown'
                tools = resp.get('tools_called', [])
                if not tools:
                    cause = 'no_tool_called'
                elif text.strip().startswith('DA EM XIN LOI') or 'OUT_OF_SCOPE' in text:
                    cause = 'out_of_scope'
                elif not any(p[:3] in text for p in exp):
                    # None of expected codes appear even partially
                    cause = 'wrong_data_returned'
                elif any(p.upper() in text for p in exp):
                    cause = 'code_in_text_but_no_match'  # shouldn't happen
                else:
                    # Check if code present without leading zeros
                    exp_stripped = [p.lstrip('0') for p in exp]
                    if any(p in text for p in exp_stripped):
                        cause = 'missing_leading_zero'
                    else:
                        cause = 'code_not_mentioned'

                fails.append({
                    'id':       c['id'],
                    'intent':   intent,
                    'query':    c['query'],
                    'exp':      exp,
                    'got':      text[:300],          # tăng từ 150 → 300
                    'full_resp': resp.get('text', '')[:800],  # full response
                    'tools':    tools,
                    'cause':    cause,
                    'http_status': r.status_code,
                })

    except Exception as e:
        results['ERROR'] += 1
        errors.append(f"{c['id']}: {e}")

    if i % 50 == 0:
        active = results['PASS'] + results['FAIL']
        pct = round(results['PASS'] / active * 100, 1) if active else 0
        print(f"{i:>3}/700  acc={pct:>5}%  pass={results['PASS']} fail={results['FAIL']} err={results['ERROR']}")

    time.sleep(2.0)

# ── Final summary ─────────────────────────────────────────────
active = results['PASS'] + results['FAIL']
pct    = round(results['PASS'] / active * 100, 1) if active else 0

print()
print("=" * 55)
print(f"FINAL: {results['PASS']}/{active} = {pct}%")
print(f"OOS_PASS={results['OOS_PASS']}  SKIP={results['SKIP']}  ERROR={results['ERROR']}")
print("=" * 55)

# ── Fails by intent ───────────────────────────────────────────
intent_total = Counter(c['intent'] for c in cases if c['expected_part_nos'])
fail_intent  = Counter(f['intent'] for f in fails)

print()
print("Fails by intent:")
for intent_key in sorted(intent_total):
    total = intent_total[intent_key]
    nfail = fail_intent.get(intent_key, 0)
    bar   = '#' * nfail
    print(f"  {intent_key:<25} {nfail:>3}/{total:<3}  {bar}")

# ── Root cause breakdown ───────────────────────────────────────
cause_counter = Counter(f['cause'] for f in fails)
print()
print("Fails by root cause:")
for cause, cnt in cause_counter.most_common():
    print(f"  {cause:<35} {cnt}")

# ── Sample fails per intent (5 each) ──────────────────────────
print()
print("Sample fails (5 per intent):")
seen_intents: Counter = Counter()
for f in fails:
    if seen_intents[f['intent']] < 5:
        seen_intents[f['intent']] += 1
        print(f"\n  [{f['intent']}] id={f['id']} cause={f['cause']}")
        print(f"    Q: {f['query']}")
        print(f"    EXP: {f['exp']}")
        print(f"    TOOLS: {f['tools']}")
        print(f"    GOT: {f['got'][:200]}")

# ── Errors ────────────────────────────────────────────────────
if errors:
    print(f"\nErrors ({len(errors)}):")
    for e in errors[:10]:
        print(f"  {e}")

# ── Save files ────────────────────────────────────────────────
with open('eval_fails.json', 'w', encoding='utf-8') as f:
    json.dump(fails, f, ensure_ascii=False, indent=2)

with open('eval_errors.json', 'w', encoding='utf-8') as f:
    json.dump(errors, f, ensure_ascii=False, indent=2)

summary = {
    'pass': results['PASS'],
    'fail': results['FAIL'],
    'accuracy_pct': pct,
    'oos_pass': results['OOS_PASS'],
    'skip': results['SKIP'],
    'error': results['ERROR'],
    'fails_by_intent': dict(fail_intent),
    'total_by_intent': dict(intent_total),
    'fails_by_cause':  dict(cause_counter),
}
with open('eval_summary.json', 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print(f"\nFails   → eval_fails.json")
print(f"Errors  → eval_errors.json")
print(f"Summary → eval_summary.json")
