#!/usr/bin/env python3
# scripts/eval_dashboard.py
# TOKINARC Eval Dashboard — HTML report từ results JSON
# ======================================================
# Usage:
#   python scripts/eval_dashboard.py results_v7.json results_p3_v2.json
#   python scripts/eval_dashboard.py results_*.json --out dashboard.html
# UTF-8 NO BOM

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def load_results(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_html(results_files: list[Path]) -> str:
    versions = []
    for f in results_files:
        try:
            data = load_results(f)
        except Exception as e:
            print(f"  Skip {f.name}: {e}")
            continue

        cases    = data.get("cases") or data.get("results") or []
        total    = len(cases)
        passed   = sum(1 for c in cases if c.get("pass") or c.get("ok"))
        score    = round(passed / total * 100, 1) if total else 0
        groups: dict[str, dict] = {}
        for c in cases:
            g = c.get("group") or c.get("category") or "OTHER"
            if g not in groups:
                groups[g] = {"total": 0, "pass": 0}
            groups[g]["total"] += 1
            if c.get("pass") or c.get("ok"):
                groups[g]["pass"] += 1

        latencies = [c.get("latency_ms", 0) for c in cases if c.get("latency_ms")]
        p50 = sorted(latencies)[len(latencies)//2] if latencies else 0
        p95 = sorted(latencies)[int(len(latencies)*0.95)] if latencies else 0

        versions.append({
            "name":    f.stem,
            "total":   total,
            "passed":  passed,
            "score":   score,
            "groups":  groups,
            "p50":     round(p50),
            "p95":     round(p95),
        })

    versions.sort(key=lambda v: v["name"])
    all_groups = sorted({g for v in versions for g in v["groups"]})

    # ── Build HTML ────────────────────────────────────────────────────────────
    rows_summary = ""
    for v in versions:
        color = "#22c55e" if v["score"] == 100 else ("#f59e0b" if v["score"] >= 95 else "#ef4444")
        rows_summary += f"""
        <tr>
          <td>{v['name']}</td>
          <td style="color:{color};font-weight:700">{v['score']}%</td>
          <td>{v['passed']}/{v['total']}</td>
          <td>{v['p50']}ms</td>
          <td>{v['p95']}ms</td>
        </tr>"""

    group_headers = "".join(f"<th>{g}</th>" for g in all_groups)
    rows_groups = ""
    for v in versions:
        cells = ""
        for g in all_groups:
            gd = v["groups"].get(g)
            if gd:
                ok = gd["pass"] == gd["total"]
                c  = "#22c55e" if ok else "#ef4444"
                cells += f'<td style="color:{c}">{gd["pass"]}/{gd["total"]}</td>'
            else:
                cells += "<td>—</td>"
        rows_groups += f"<tr><td>{v['name']}</td>{cells}</tr>"

    chart_labels = json.dumps([v["name"] for v in versions])
    chart_scores = json.dumps([v["score"] for v in versions])
    chart_p50    = json.dumps([v["p50"] for v in versions])

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    latest = versions[-1] if versions else {}

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TOKINARC Eval Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  body{{font-family:system-ui,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}}
  .header{{background:#1e293b;padding:24px 32px;border-bottom:1px solid #334155}}
  h1{{margin:0;font-size:1.5rem;color:#f8fafc}}
  .sub{{color:#94a3b8;font-size:.85rem;margin-top:4px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;padding:24px 32px}}
  .card{{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}}
  .card-label{{font-size:.75rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}}
  .card-value{{font-size:2rem;font-weight:700;margin-top:4px}}
  .green{{color:#22c55e}} .yellow{{color:#f59e0b}} .red{{color:#ef4444}} .blue{{color:#38bdf8}}
  .section{{padding:0 32px 32px}}
  h2{{color:#cbd5e1;font-size:1rem;margin-bottom:12px;border-bottom:1px solid #334155;padding-bottom:8px}}
  table{{width:100%;border-collapse:collapse;font-size:.85rem}}
  th{{background:#0f172a;padding:8px 12px;text-align:left;color:#64748b;font-weight:500}}
  td{{padding:8px 12px;border-bottom:1px solid #1e293b}}
  tr:hover td{{background:#1e293b55}}
  .chart-wrap{{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155;margin-bottom:24px}}
</style>
</head>
<body>
<div class="header">
  <h1>🔬 TOKINARC Eval Dashboard</h1>
  <div class="sub">Generated {generated} · {len(versions)} versions</div>
</div>

<div class="grid">
  <div class="card">
    <div class="card-label">Latest Score</div>
    <div class="card-value {'green' if latest.get('score',0)==100 else 'yellow'}">{latest.get('score','—')}%</div>
  </div>
  <div class="card">
    <div class="card-label">Cases</div>
    <div class="card-value blue">{latest.get('passed','—')}/{latest.get('total','—')}</div>
  </div>
  <div class="card">
    <div class="card-label">Latency p50</div>
    <div class="card-value blue">{latest.get('p50','—')}ms</div>
  </div>
  <div class="card">
    <div class="card-label">Latency p95</div>
    <div class="card-value {'green' if latest.get('p95',9999)<4000 else 'yellow'}">{latest.get('p95','—')}ms</div>
  </div>
</div>

<div class="section">
  <div class="chart-wrap">
    <h2>Score Trend</h2>
    <canvas id="scoreChart" height="80"></canvas>
  </div>
  <div class="chart-wrap">
    <h2>Latency p50 Trend (ms)</h2>
    <canvas id="latencyChart" height="80"></canvas>
  </div>

  <h2>Version Summary</h2>
  <table>
    <thead><tr><th>Version</th><th>Score</th><th>Pass/Total</th><th>p50</th><th>p95</th></tr></thead>
    <tbody>{rows_summary}</tbody>
  </table>

  <h2 style="margin-top:24px">Group Breakdown</h2>
  <table>
    <thead><tr><th>Version</th>{group_headers}</tr></thead>
    <tbody>{rows_groups}</tbody>
  </table>
</div>

<script>
const labels = {chart_labels};
const scores = {chart_scores};
const p50s   = {chart_p50};
const cfg = (data, color, label) => ({{
  type:'line', data:{{labels, datasets:[{{label, data, borderColor:color,
  backgroundColor:color+'22', tension:.3, pointRadius:4, fill:true}}]}},
  options:{{responsive:true, plugins:{{legend:{{display:false}}}},
    scales:{{y:{{grid:{{color:'#334155'}}, ticks:{{color:'#94a3b8'}}}},
             x:{{grid:{{color:'#334155'}}, ticks:{{color:'#94a3b8'}}}}}}}}
}});
new Chart(document.getElementById('scoreChart'), cfg(scores,'#22c55e','Score %'));
new Chart(document.getElementById('latencyChart'), cfg(p50s,'#38bdf8','p50 ms'));
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="TOKINARC Eval Dashboard Generator")
    parser.add_argument("files", nargs="+", type=Path, help="results_*.json files")
    parser.add_argument("--out", type=Path, default=Path("eval_dashboard.html"))
    args = parser.parse_args()

    files = sorted(args.files)
    print(f"Building dashboard from {len(files)} file(s)...")
    html = build_html(files)
    args.out.write_text(html, encoding="utf-8")
    print(f"✅ Dashboard → {args.out}")


if __name__ == "__main__":
    main()
