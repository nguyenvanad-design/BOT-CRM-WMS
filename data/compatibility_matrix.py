"""
compatibility_matrix.py — DEPRECATED STUB
==========================================
[v2026-05-21] File này đã được DEPRECATE.
[v2026-05-28] Updated references v11k → v16.

Lý do:
  Toàn bộ data trong matrix v11g (PART_NODES, COMPATIBILITY_EDGES, TPMS, 
  NEGATIVE_RULES, CONSUMABLE_SETS, PROCESS_EDGES, GAS_FLOW_EDGES, 
  CATEGORY_VOCABULARY) đã được EMBED vào tokinarc_data_v16.json.

  Matrix v11g chỉ có 131 parts trong khi data v16 có 838 parts (lệch 84%).
  Sync lại matrix là tốn công vô ích — single source of truth là JSON.

  v16 stats: 121 torches | 838 parts | 7588 compat edges | 1518 TPMs |
             17 negative rules | 359 process edges | 24 gas flow edges |
             9 consumable sets | 35 category vocab entries

Migration guide:
  CŨ:                                  MỚI:
  ─────────────────────────────────────────────────────────────────────
  from compatibility_matrix import     from tokinarc_cer import get_cer
      PART_NODES, TORCH_MODELS,        cer = get_cer()  # loads v16 JSON
      COMPATIBILITY_EDGES,             # cer.get_part(), cer.get_torch(),
      TPMS, NEGATIVE_RULES, ...        # cer.check_compatibility(), etc.

  PART_NODES                       →   cer._raw["parts"]
  TORCH_MODELS                     →   cer._raw["torches"]
  COMPATIBILITY_EDGES              →   cer._raw["compatibility_edges"]
  TORCH_PART_MAPPINGS              →   cer._raw["torch_part_mappings"]
  NEGATIVE_COMPATIBILITY_RULES     →   cer._raw["negative_rules"]
  CONSUMABLE_SETS                  →   cer._raw["consumable_sets"]
  PROCESS_EDGES                    →   cer._raw["process_edges"]
  GAS_FLOW_EDGES                   →   cer._raw["gas_flow_edges"]
  CATEGORY_VOCABULARY              →   cer._raw["category_vocabulary"]

Backward compat:
  File này expose các module-level constants để code cũ vẫn chạy được.
  Nội dung load từ tokinarc_data_v16.json (KHÔNG phải từ matrix v11g cũ).
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import List, Dict, Any

# Default data path — overridable via env var TOKINARC_DATA_PATH
import os
_DEFAULT_DATA_PATH = os.environ.get(
    "TOKINARC_DATA_PATH",
    "/home/claude/tokinarc_data_v16.json"
)


def _load_data(path: str = None) -> dict:
    """Lazy-load data v16 JSON."""
    path = path or _DEFAULT_DATA_PATH
    if not Path(path).exists():
        # Fallback paths
        for p in ["./tokinarc_data_v16.json",
                  "./data/tokinarc_data_v16.json",
                  "../data/tokinarc_data_v16.json"]:
            if Path(p).exists():
                path = p
                break
        else:
            raise FileNotFoundError(
                f"tokinarc_data_v16.json not found at {path}. "
                f"Set TOKINARC_DATA_PATH env var or place file in cwd."
            )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# Lazy singleton — chỉ load khi access lần đầu
_data_cache: dict = None

def _get_data() -> dict:
    global _data_cache
    if _data_cache is None:
        warnings.warn(
            "compatibility_matrix.py is DEPRECATED. "
            "Migrate to tokinarc_cer.get_cer() for production use.",
            DeprecationWarning,
            stacklevel=2
        )
        _data_cache = _load_data()
    return _data_cache


# Module-level constants (backward compat with old matrix v11g)
# Code cũ làm:  from compatibility_matrix import PART_NODES
# __getattr__ hook (PEP 562) intercept và load từ JSON

def __getattr__(name: str) -> Any:
    data = _get_data()
    mapping = {
        "PART_NODES":                  "parts",
        "TORCH_MODELS":                "torches",
        "COMPATIBILITY_EDGES":         "compatibility_edges",
        "TORCH_PART_MAPPINGS":         "torch_part_mappings",
        "NEGATIVE_COMPATIBILITY_RULES": "negative_rules",
        "CONSUMABLE_SETS":             "consumable_sets",
        "PROCESS_EDGES":               "process_edges",
        "GAS_FLOW_EDGES":              "gas_flow_edges",
        "CATEGORY_VOCABULARY":         "category_vocabulary",
    }
    if name in mapping:
        return data.get(mapping[name], [])
    raise AttributeError(f"module 'compatibility_matrix' has no attribute {name!r}")


# Convenient accessor functions
def get_torch_models() -> List[dict]:
    return _get_data().get("torches", [])

def get_part_nodes() -> List[dict]:
    return _get_data().get("parts", [])

def get_compatibility_edges() -> List[dict]:
    return _get_data().get("compatibility_edges", [])

def get_torch_part_mappings() -> List[dict]:
    return _get_data().get("torch_part_mappings", [])

def get_negative_rules() -> List[dict]:
    return _get_data().get("negative_rules", [])

def get_consumable_sets() -> List[dict]:
    return _get_data().get("consumable_sets", [])

def get_process_edges() -> List[dict]:
    return _get_data().get("process_edges", [])

def get_gas_flow_edges() -> List[dict]:
    return _get_data().get("gas_flow_edges", [])

def get_category_vocabulary() -> List[dict]:
    return _get_data().get("category_vocabulary", [])


def get_stats() -> Dict[str, int]:
    """Return data stats from v16 JSON."""
    data = _get_data()
    return {
        "torches":          len(data.get("torches", [])),
        "parts":            len(data.get("parts", [])),
        "compat_edges":     len(data.get("compatibility_edges", [])),
        "tpms":             len(data.get("torch_part_mappings", [])),
        "negative_rules":   len(data.get("negative_rules", [])),
        "consumable_sets":  len(data.get("consumable_sets", [])),
        "process_edges":    len(data.get("process_edges", [])),
        "gas_flow_edges":   len(data.get("gas_flow_edges", [])),
        "category_vocab":   len(data.get("category_vocabulary", [])),
        "version":          data.get("meta", {}).get("schema_version", "?"),
    }


if __name__ == "__main__":
    print("compatibility_matrix.py — DEPRECATED stub")
    print("Loading from tokinarc_data_v16.json...")
    stats = get_stats()
    print(f"\nStats:")
    for k, v in stats.items():
        print(f"  {k:<20s} {v}")
    print(f"\nUse `from tokinarc_cer import get_cer` for new code.")
