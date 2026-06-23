# ═══════════════════════════════════════════════════════════════════════════
# Tokinarc Bot — System Verification Script
# Usage:
#   .\verify_system.ps1              # Run all sections
#   .\verify_system.ps1 -Section 1   # Run only section N (1-6)
#   .\verify_system.ps1 -SkipLive    # Bỏ qua live API smoke test
# ═══════════════════════════════════════════════════════════════════════════
param(
    [int]$Section = 0,
    [switch]$SkipLive,
    [string]$ApiKey = $env:TOKINARC_API_KEY,
    [string]$BaseUrl = "http://192.168.1.100:8080"
)

$ErrorActionPreference = "Continue"
$script:Pass = 0; $script:Fail = 0; $script:Warn = 0

# Set PYTHONPATH để Python tìm được module ở cả root và core\
# Windows dùng ';' làm separator (không phải ':' như Linux)
$env:PYTHONPATH = ".;.\core"

function Write-Section($title) {
    Write-Host ""
    Write-Host ("═" * 70) -ForegroundColor Cyan
    Write-Host "  $title" -ForegroundColor Cyan
    Write-Host ("═" * 70) -ForegroundColor Cyan
}
function Pass($msg) { Write-Host "  ✅ $msg" -ForegroundColor Green;  $script:Pass++ }
function Fail($msg) { Write-Host "  ❌ $msg" -ForegroundColor Red;    $script:Fail++ }
function Warn($msg) { Write-Host "  ⚠️  $msg" -ForegroundColor Yellow; $script:Warn++ }
function Info($msg) { Write-Host "  ℹ️  $msg" -ForegroundColor Gray }

$RunAll = ($Section -eq 0)

# ─────────────────────────────────────────────────────────────────────────
# Section 1: File integrity (size, mtime, syntax)
# ─────────────────────────────────────────────────────────────────────────
if ($RunAll -or $Section -eq 1) {
Write-Section "[1/6] FILE INTEGRITY — size, mtime, syntax"

$files = @(
    @{ Path = "data\tokinarc_data_v20.json"; MinKB = 3000; Type = "json"  },
    @{ Path = "core\data_store.py";          MinKB = 60;   Type = "python" },
    @{ Path = "core\tokinarc_cer.py";        MinKB = 20;   Type = "python" },
    @{ Path = "core\tool_wrappers.py";       MinKB = 60;   Type = "python" },
    @{ Path = "core\system_prompts.py";      MinKB = 50;   Type = "python" },
    @{ Path = "core\llm_orchestrator_v2.py"; MinKB = 60;   Type = "python" },
    @{ Path = "core\fuzzy_corrector.py";     MinKB = 30;   Type = "python" },
    @{ Path = "main.py";                     MinKB = 10;   Type = "python" }
)

foreach ($f in $files) {
    if (-not (Test-Path $f.Path)) {
        # Try alternative paths
        $alt = $f.Path -replace '^core\\', ''
        if (Test-Path $alt) { $f.Path = $alt }
    }
    if (-not (Test-Path $f.Path)) {
        Fail "Missing: $($f.Path)"
        continue
    }
    $size = (Get-Item $f.Path).Length / 1024
    $mtime = (Get-Item $f.Path).LastWriteTime
    $sizeOk = $size -ge $f.MinKB
    $marker = if ($sizeOk) { "✓" } else { "⚠" }
    Write-Host ("    {0}  {1,-40} {2,8:N1} KB   {3}" -f $marker, $f.Path, $size, $mtime) -ForegroundColor Gray

    if ($f.Type -eq "python") {
        $check = python -c "import ast; ast.parse(open(r'$($f.Path)', encoding='utf-8').read())" 2>&1
        if ($LASTEXITCODE -eq 0) { Pass "Python syntax: $($f.Path)" }
        else { Fail "Syntax error: $($f.Path) — $check" }
    } elseif ($f.Type -eq "json") {
        $check = python -c "import json; json.load(open(r'$($f.Path)', encoding='utf-8'))" 2>&1
        if ($LASTEXITCODE -eq 0) { Pass "JSON valid: $($f.Path)" }
        else { Fail "JSON parse error: $($f.Path) — $check" }
    }
}
}

# ─────────────────────────────────────────────────────────────────────────
# Section 2: Data v20 content audit
# ─────────────────────────────────────────────────────────────────────────
if ($RunAll -or $Section -eq 2) {
Write-Section "[2/6] DATA v20 — robot_compatibility coverage + meta"

$dataPath = "data\tokinarc_data_v20.json"
if (-not (Test-Path $dataPath)) {
    Fail "Data file not found: $dataPath"
} else {
    $report = python -c @"
import json, sys
with open(r'$dataPath', encoding='utf-8') as f:
    d = json.load(f)

meta = d.get('meta', {})
print(f'META.version={meta.get(\"version\")}')
print(f'META.last_updated={meta.get(\"last_updated\")}')
cl = meta.get('changelog', [])
if isinstance(cl, list) and cl:
    last = cl[-1]
    if isinstance(last, dict):
        print(f'META.changelog_last={last.get(\"version\")}|{last.get(\"date\")}')

torches = d['torches']
print(f'TOTAL_TORCHES={len(torches)}')

ma1440 = sum(1 for t in torches if 'MA1440' in (t.get('robot_compatibility') or []))
ar1440 = sum(1 for t in torches if 'AR1440' in (t.get('robot_compatibility') or []))
print(f'MATCH_MA1440={ma1440}')
print(f'MATCH_AR1440={ar1440}')

# Verify YMENS + TR have Option B
samples = ['YMENS-300R','TR-300R','YMSA-508R','TK-508RR','ACC-308RR']
for code in samples:
    for t in torches:
        if t.get('model_code')==code:
            rc = t.get('robot_compatibility', [])
            n = len(rc) if isinstance(rc, list) else 0
            print(f'TORCH_{code}={n}|{\",\".join(map(str,rc[:3]))}')
            break

robot_aliases = meta.get('robot_aliases') or {}
print(f'ROBOT_ALIASES={len(robot_aliases)}')
key_aliases = ['1.4m', '1,4m', '1.4 mét', '1440']
for k in key_aliases:
    v = robot_aliases.get(k, '(missing)')
    print(f'ALIAS[{k}]={v}')
"@ 2>&1

    $parsed = @{}
    foreach ($line in $report -split "`r?`n") {
        if ($line -match '^(\w[\w\.]*?)=(.*)$') {
            $parsed[$matches[1]] = $matches[2]
        }
    }

    # Checks
    if ($parsed['META.version'] -eq 'v20') { Pass "meta.version = 'v20'" }
    else { Fail "meta.version = '$($parsed['META.version'])' (expected 'v20')" }

    if ($parsed['META.last_updated'] -and $parsed['META.last_updated'] -ne 'None') {
        Pass "meta.last_updated = $($parsed['META.last_updated'])"
    } else { Fail "meta.last_updated missing" }

    if ($parsed['META.changelog_last']) {
        Pass "changelog last entry: $($parsed['META.changelog_last'])"
    } else { Warn "no changelog entries" }

    Info "Total torches: $($parsed['TOTAL_TORCHES'])"

    $ma = [int]$parsed['MATCH_MA1440']
    $ar = [int]$parsed['MATCH_AR1440']
    if ($ma -ge 33) { Pass "Torches matching MA1440: $ma (expected ≥33)" }
    else { Fail "Torches matching MA1440: $ma (expected ≥33 after Option B)" }
    if ($ar -ge 33) { Pass "Torches matching AR1440: $ar (expected ≥33)" }
    else { Fail "Torches matching AR1440: $ar (expected ≥33 after Option B)" }

    # YMENS should have ≥9 robots after Option B
    $ymens = $parsed['TORCH_YMENS-300R']
    if ($ymens -match '^(\d+)\|') {
        $n = [int]$matches[1]
        if ($n -ge 9) { Pass "YMENS-300R has $n robots (Option B applied)" }
        else { Fail "YMENS-300R has $n robots (expected ≥9 after Option B)" }
    }

    $tr = $parsed['TORCH_TR-300R']
    if ($tr -match '^(\d+)\|') {
        $n = [int]$matches[1]
        if ($n -ge 11) { Pass "TR-300R has $n robots (Option B applied)" }
        else { Fail "TR-300R has $n robots (expected ≥11 after Option B)" }
    }

    # Robot aliases
    $aliasCount = [int]$parsed['ROBOT_ALIASES']
    if ($aliasCount -ge 30) { Pass "meta.robot_aliases has $aliasCount entries" }
    else { Warn "meta.robot_aliases only $aliasCount entries (expected ≥30)" }

    if ($parsed['ALIAS[1.4m]'] -eq 'MA1440') { Pass "alias '1.4m' → MA1440" }
    else { Fail "alias '1.4m' missing or wrong: $($parsed['ALIAS[1.4m]'])" }
    if ($parsed['ALIAS[1,4m]'] -eq 'MA1440') { Pass "alias '1,4m' → MA1440" }
    else { Fail "alias '1,4m' missing or wrong" }
}
}

# ─────────────────────────────────────────────────────────────────────────
# Section 3: Code patch markers
# ─────────────────────────────────────────────────────────────────────────
if ($RunAll -or $Section -eq 3) {
Write-Section "[3/6] CODE PATCHES — verify all fixes in place"

# Helper to find file (try core\ then root)
function Get-CodeFile($name) {
    $p1 = "core\$name"; $p2 = $name
    if (Test-Path $p1) { return $p1 }
    if (Test-Path $p2) { return $p2 }
    return $null
}

# tool_wrappers.py — Fix #1 + Fix B
$tw = Get-CodeFile "tool_wrappers.py"
if ($tw) {
    $code = Get-Content $tw -Raw
    if ($code -match '_CC_BAND')           { Pass "[tool_wrappers] _CC_BAND defined" } else { Fail "[tool_wrappers] _CC_BAND missing" }
    if ($code -match 'def _part_compatible'){ Pass "[tool_wrappers] _part_compatible() exists" } else { Fail "[tool_wrappers] _part_compatible() missing" }
    if ($code -match 'def _robot_match')   { Pass "[tool_wrappers] _robot_match() exists" } else { Fail "[tool_wrappers] _robot_match() missing" }
    if ($code -match 'retry_dropped')      { Pass "[tool_wrappers] get_torches soft-fail retry" } else { Fail "[tool_wrappers] retry logic missing" }
    if ($code -match '_KNOWN_ROBOT_MODELS'){ Pass "[tool_wrappers] _KNOWN_ROBOT_MODELS defined" } else { Fail "missing" }
    if ($code -match '_ROBOT_ALIASES_FALLBACK') { Pass "[tool_wrappers] fallback alias map" } else { Fail "missing" }
    if ($code -match '"1\.4 mét":\s*"MA1440"') { Pass "[tool_wrappers] alias '1.4 mét' → MA1440" } else { Warn "alias text not exact match" }
} else { Fail "tool_wrappers.py not found" }

# data_store.py — _installation patch
$ds = Get-CodeFile "data_store.py"
if ($ds) {
    $code = Get-Content $ds -Raw
    if ($code -match 'Bug fix 2026-06') { Pass "[data_store] _installation bug fix comment" } else { Fail "[data_store] bug fix comment missing" }
    # Check _CC_BAND appears inside _installation
    $instSection = ""
    if ($code -match '(?ms)def _installation\(self.*?def \w+\(self') {
        $instSection = $matches[0]
        if ($instSection -match '_CC_BAND')      { Pass "[data_store] _CC_BAND in _installation" } else { Fail "_CC_BAND not in _installation" }
        if ($instSection -match '_part_compat')  { Pass "[data_store] _part_compat helper in _installation" } else { Fail "missing" }
        if ($instSection -match '_resolve_torch_model') { Pass "[data_store] resolves torch via _resolve_torch_model" } else { Fail "missing" }
        if ($instSection -match 'Safety net|safety net') { Pass "[data_store] safety net fallback" } else { Warn "no safety net comment" }
    } else { Fail "_installation method not found" }
} else { Fail "data_store.py not found" }

# tokinarc_cer.py — resolve_torch alias
$cer = Get-CodeFile "tokinarc_cer.py"
if ($cer) {
    $code = Get-Content $cer -Raw
    if ($code -match 'def get_torch\(self,')     { Pass "[cer] get_torch() exists" } else { Fail "missing" }
    if ($code -match 'def resolve_torch\(self,') { Pass "[cer] resolve_torch() added" } else { Fail "[cer] resolve_torch() MISSING" }
} else { Fail "tokinarc_cer.py not found" }

# system_prompts.py — rule [13] về get_torches over-specify
$sp = Get-CodeFile "system_prompts.py"
if ($sp) {
    $code = Get-Content $sp -Raw
    if ($code -match 'KHÔNG over-specify') { Pass "[system_prompts] rule about get_torches over-specify" } else { Fail "rule [13] over-specify MISSING" }
    if ($code -match '1,4 mét|1\.4 mét') { Pass "[system_prompts] mentions '1,4 mét' / '1.4 mét' example" } else { Warn "1.4m example not found" }
    if ($code -match 'AR1440E.*YMENS|YMENS.*AR1440E') { Pass "[system_prompts] AR1440E → YMENS example" } else { Warn "AR1440E example weak" }
} else { Fail "system_prompts.py not found" }

# main.py — 4096 max_length + 422 handler
$mp = "main.py"
if (Test-Path $mp) {
    $code = Get-Content $mp -Raw
    if ($code -match 'max_length\s*=\s*4096') { Pass "[main] max_length = 4096" } else { Warn "max_length not 4096" }
    if ($code -match 'RequestValidationError|validation_exception_handler') { Pass "[main] 422 validation handler" } else { Warn "no custom 422 handler" }
} else { Warn "main.py not found in current dir" }

# llm_orchestrator_v2.py — MAX_TOOL_CALLS
$llm = Get-CodeFile "llm_orchestrator_v2.py"
if ($llm) {
    $code = Get-Content $llm -Raw
    if ($code -match 'MAX_TOOL_CALLS') { Pass "[orchestrator] MAX_TOOL_CALLS cap (runaway guard)" } else { Fail "MAX_TOOL_CALLS missing" }
}
}

# ─────────────────────────────────────────────────────────────────────────
# Section 4: Import test (modules load, key methods callable)
# ─────────────────────────────────────────────────────────────────────────
if ($RunAll -or $Section -eq 4) {
Write-Section "[4/6] MODULE IMPORTS + RUNTIME CHECK"

$importTest = python -c @"
import sys, os
sys.path.insert(0, '.')
sys.path.insert(0, 'core')

try:
    from data_store import DataStore, _resolve_data_path, _find_latest_data_file
    print('IMPORT_data_store=ok')

    data_path = _resolve_data_path()
    print(f'DATA_PATH={data_path}')

    ds = DataStore(data_path)
    print(f'DS_TORCHES={len(ds.torches)}')
    print(f'DS_PARTS={len(ds.parts)}')

    meta = getattr(ds, 'meta', {})
    if isinstance(meta, dict):
        amap = meta.get('robot_aliases') or {}
        print(f'DS_ALIASES={len(amap)}')

    # Test torch model fuzzy resolve
    resolved = ds._resolve_torch_model('ymsa508r')
    print(f'RESOLVE_ymsa508r={resolved}')
    resolved2 = ds._resolve_torch_model('YMSA-508R')
    print(f'RESOLVE_YMSA-508R={resolved2}')
except Exception as e:
    print(f'IMPORT_data_store=error|{e}')

try:
    from tokinarc_cer import TokinarcCER
    print('IMPORT_cer=ok')
    cer = TokinarcCER(ds=ds)
    has_resolve = hasattr(cer, 'resolve_torch') and callable(getattr(cer, 'resolve_torch', None))
    print(f'CER_resolve_torch={has_resolve}')
    t = cer.resolve_torch('YMSA-508R')
    print(f'CER_resolve_result={t is not None}')
    if t:
        eco = getattr(t, 'ecosystem', '?')
        cc  = getattr(t, 'current_class', '?')
        print(f'YMSA-508R_eco={eco}|cc={cc}')
except Exception as e:
    print(f'IMPORT_cer=error|{e}')

try:
    from tool_wrappers import _resolve_robot, _KNOWN_ROBOT_MODELS, get_torches, set_data_store
    print('IMPORT_tool_wrappers=ok')
    set_data_store(ds)
    r1 = _resolve_robot('1.4 mét')
    print(f'RESOLVE_1.4_mét={r1}')
    r2 = _resolve_robot('1,4m')
    print(f'RESOLVE_1,4m={r2}')
    r3 = _resolve_robot('yaskwa')  # typo
    print(f'RESOLVE_yaskwa={r3}')
    print(f'KNOWN_ROBOTS={len(_KNOWN_ROBOT_MODELS)}')

    # Live tool call: get_torches with '1.4m'
    result = get_torches(robot_model='1.4m')
    if result.get('success'):
        n = result.get('data', {}).get('total', 0)
        print(f'GET_TORCHES_1.4m={n}')
    else:
        print(f'GET_TORCHES_1.4m=fail|{result.get(\"error\",\"?\")}')

    # YMENS test
    result2 = get_torches(robot_model='AR1440E')
    if result2.get('success'):
        n = result2.get('data', {}).get('total', 0)
        print(f'GET_TORCHES_AR1440E={n}')
except Exception as e:
    print(f'IMPORT_tool_wrappers=error|{e}')
"@ 2>&1

    $parsed = @{}
    foreach ($line in $importTest -split "`r?`n") {
        if ($line -match '^(\w[\w\.]*?)=(.*)$') {
            $parsed[$matches[1]] = $matches[2]
        } else {
            Write-Host "    $line" -ForegroundColor Gray
        }
    }

    if ($parsed['IMPORT_data_store'] -eq 'ok') { Pass "DataStore imports cleanly" } else { Fail "DataStore import failed: $($parsed['IMPORT_data_store'])" }
    if ($parsed['DATA_PATH'])                   { Info "Resolved data path: $($parsed['DATA_PATH'])" }
    if ([int]$parsed['DS_TORCHES'] -ge 120)     { Pass "DataStore loaded $($parsed['DS_TORCHES']) torches" } else { Fail "Expected ≥120 torches, got $($parsed['DS_TORCHES'])" }
    if ([int]$parsed['DS_PARTS'] -ge 100)       { Pass "DataStore loaded $($parsed['DS_PARTS']) parts" } else { Warn "Parts count low: $($parsed['DS_PARTS'])" }
    if ([int]$parsed['DS_ALIASES'] -ge 30)      { Pass "Robot aliases loaded: $($parsed['DS_ALIASES'])" } else { Warn "alias count: $($parsed['DS_ALIASES'])" }

    if ($parsed['RESOLVE_ymsa508r'] -eq 'YMSA-508R') { Pass "Fuzzy resolve 'ymsa508r' → YMSA-508R" } else { Warn "fuzzy resolve result: $($parsed['RESOLVE_ymsa508r'])" }

    if ($parsed['IMPORT_cer'] -eq 'ok')                { Pass "CER imports cleanly" } else { Fail "CER import failed" }
    if ($parsed['CER_resolve_torch'] -eq 'True')      { Pass "CER.resolve_torch() callable" } else { Fail "CER.resolve_torch missing" }
    if ($parsed['CER_resolve_result'] -eq 'True')     { Pass "CER.resolve_torch('YMSA-508R') returns object" } else { Fail "resolve_torch returned None" }
    if ($parsed['YMSA-508R_eco'] -eq 'N')             { Pass "YMSA-508R ecosystem = N" } else { Warn "YMSA-508R eco: $($parsed['YMSA-508R_eco'])" }
    if ($parsed['YMSA-508R_eco'] -match '^N$' -and $parsed -contains 'YMSA-508R_eco') {
        # split combined line
    }

    if ($parsed['IMPORT_tool_wrappers'] -eq 'ok') { Pass "tool_wrappers imports cleanly" } else { Fail "tool_wrappers failed" }
    if ($parsed['RESOLVE_1.4_mét'] -eq 'MA1440')  { Pass "_resolve_robot('1.4 mét') → MA1440" } else { Fail "got: $($parsed['RESOLVE_1.4_mét'])" }
    if ($parsed['RESOLVE_1,4m'] -eq 'MA1440')     { Pass "_resolve_robot('1,4m') → MA1440" } else { Fail "got: $($parsed['RESOLVE_1,4m'])" }

    $n_1_4 = [int]$parsed['GET_TORCHES_1.4m']
    if ($n_1_4 -ge 33) { Pass "get_torches(robot_model='1.4m') returned $n_1_4 torches (≥33 after Option B)" }
    elseif ($n_1_4 -ge 26) { Warn "get_torches('1.4m') = $n_1_4 (Option B may not be applied — expected ≥33)" }
    else { Fail "get_torches('1.4m') = $n_1_4 (BROKEN — expected ≥26)" }

    $n_e = [int]$parsed['GET_TORCHES_AR1440E']
    if ($n_e -ge 30) { Pass "get_torches(robot_model='AR1440E') returned $n_e torches" }
    elseif ($n_e -ge 5) { Info "get_torches('AR1440E') = $n_e — pre-Option-B behavior (5 YMENS only)" }
    else { Fail "get_torches('AR1440E') broken: $n_e" }
}

# ─────────────────────────────────────────────────────────────────────────
# Section 5: pytest regression
# ─────────────────────────────────────────────────────────────────────────
if ($RunAll -or $Section -eq 5) {
Write-Section "[5/6] PYTEST REGRESSION — replacement steps compat"

if (Test-Path "tests\test_replacement_steps_compat.py") {
    $testOut = python -m pytest tests\test_replacement_steps_compat.py -v --tb=short 2>&1
    $exit = $LASTEXITCODE
    Write-Host ($testOut | Out-String) -ForegroundColor Gray
    if ($exit -eq 0) { Pass "All pytest tests passed (Fix #1 still active)" }
    else { Fail "pytest exited with code $exit — Fix #1 may be regressed" }
} else {
    Warn "tests\test_replacement_steps_compat.py not found — skip regression"
}
}

# ─────────────────────────────────────────────────────────────────────────
# Section 6: Live API smoke test (requires running server)
# ─────────────────────────────────────────────────────────────────────────
if (($RunAll -or $Section -eq 6) -and -not $SkipLive) {
Write-Section "[6/6] LIVE API SMOKE TEST ($BaseUrl)"

if (-not $ApiKey) {
    Warn "TOKINARC_API_KEY env var not set — skip live test. Set with: \$env:TOKINARC_API_KEY='...'"
} else {
    $hdrs = @{ 'X-API-Key' = $ApiKey; 'Content-Type' = 'application/json' }
    # Health endpoint
    try {
        $resp = Invoke-WebRequest -Uri "$BaseUrl/openapi.json" -Headers $hdrs -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { Pass "Server reachable at $BaseUrl (openapi.json 200)" }
        else { Warn "openapi.json returned $($resp.StatusCode)" }
    } catch {
        Fail "Server unreachable: $($_.Exception.Message)"
        Write-Host "  → Start with: uvicorn main:app --host 192.168.1.100 --port 8080 --log-level info" -ForegroundColor Yellow
    }

    # 4 smoke-test queries
    $queries = @(
        @{ Q = "súng hàn cho robot Yaskawa 1.4 mét"; Expect = "≥33 torches in response, includes YMENS or TR" },
        @{ Q = "Sơ đồ kỹ thuật, lắp ráp YMSA-508R";  Expect = "NO 016051 or 016503 (350A leak fix)" },
        @{ Q = "Robot AR1440E dùng súng nào";          Expect = "YMENS + (after Option B) others too" },
        @{ Q = "TK-508RR cần liner gì";                Expect = "Liner 500A compatible, NOT 350A" }
    )

    foreach ($q in $queries) {
        Write-Host ""
        Info "Query: $($q.Q)"
        Info "Expect: $($q.Expect)"
        $body = @{ query = $q.Q; session_id = "verify_$([guid]::NewGuid().ToString().Substring(0,8))" } | ConvertTo-Json -Compress
        try {
            $resp = Invoke-WebRequest -Uri "$BaseUrl/api/v2/query" -Method POST -Headers $hdrs -Body $body -TimeoutSec 30 -UseBasicParsing -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                $j = $resp.Content | ConvertFrom-Json
                $text = $j.response
                if (-not $text) { $text = $j.bot_response }
                if ($text) {
                    $preview = $text.Substring(0, [Math]::Min(200, $text.Length))
                    Write-Host "    Response (200 chars): $preview..." -ForegroundColor DarkGray

                    # Heuristic checks
                    if ($q.Q -match '1\.4 mét') {
                        $hits = ([regex]::Matches($text, '\b(YMXA|YMSA|TK-|ACC-|SRCT|YMENS|TR-)') | ForEach-Object { $_.Value } | Sort-Object -Unique).Count
                        if ($hits -ge 3) { Pass "Mentions ≥3 distinct torch families" } else { Warn "only $hits families mentioned" }
                    }
                    if ($q.Q -match 'YMSA-508R') {
                        if ($text -match '016051|016503') { Fail "LEAK: 350A part code found in 500A torch response" }
                        else { Pass "No 350A leak in YMSA-508R response" }
                    }
                } else { Warn "Response empty" }
            } else { Warn "HTTP $($resp.StatusCode)" }
        } catch {
            Fail "Query failed: $($_.Exception.Message)"
        }
    }
}
} elseif ($SkipLive) {
    Info "Live API smoke test skipped (-SkipLive)"
}

# ─────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host ("═" * 70) -ForegroundColor Cyan
Write-Host "  SUMMARY" -ForegroundColor Cyan
Write-Host ("═" * 70) -ForegroundColor Cyan
Write-Host "  Pass:  $script:Pass" -ForegroundColor Green
Write-Host "  Warn:  $script:Warn" -ForegroundColor Yellow
Write-Host "  Fail:  $script:Fail" -ForegroundColor Red
Write-Host ""

if ($script:Fail -eq 0 -and $script:Warn -eq 0) {
    Write-Host "  🎉 ALL CHECKS PASSED — system is healthy" -ForegroundColor Green
    exit 0
} elseif ($script:Fail -eq 0) {
    Write-Host "  ✅ No failures, but $script:Warn warnings — review above" -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "  ❌ $script:Fail FAILURES — fix before deploying" -ForegroundColor Red
    exit 1
}
