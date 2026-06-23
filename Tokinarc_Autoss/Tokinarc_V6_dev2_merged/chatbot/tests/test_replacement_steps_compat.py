"""
tests/test_replacement_steps_compat.py
Regression tests cho bug fix Patch #1.
"""

import pytest
from core.tool_wrappers import get_replacement_steps


def _extract_part_codes(result: dict) -> set:
    assert result.get("success"), f"Tool call failed: {result}"
    parts = result.get("data", {}).get("related_parts", [])
    return {p.get("tokin_part_no") for p in parts if p.get("tokin_part_no")}


def test_508R_no_350A_tip_body_leak():
    """YMSA-508R (500A) -> TipBody response phai KHONG chua TK-308RR (350A)."""
    result = get_replacement_steps(category="TipBody", torch_model="YMSA-508R")
    codes = _extract_part_codes(result)
    assert "016403" in codes, f"Missing compatible 500A part 016403. Got: {codes}"
    assert "016051" not in codes, f"BUG: 350A part 016051 (TK-308RR) leaked! Got: {codes}"
    assert "016503" not in codes, f"BUG: 350A part 016503 (ACC-308RR) leaked! Got: {codes}"


def test_508R_no_350A_liner_leak():
    """YMSA-508R -> Liner khong duoc lan liner 350A (016076, 037002, 037003).
    NOTE: 016126 ten goi y '308RR' nhung metadata.current_class='500A' (variant
    dây 1.4-1.6mm) — duoc giu lai dung theo data thuc te.
    """
    result = get_replacement_steps(category="Liner", torch_model="YMSA-508R")
    codes = _extract_part_codes(result)
    assert "016076" not in codes, f"BUG: 350A liner 016076 leaked. Got: {codes}"
    assert "037002" not in codes, f"BUG: 200A liner 037002 leaked. Got: {codes}"
    assert "037003" not in codes, f"BUG: 350A liner 037003 leaked. Got: {codes}"
    # Sanity: phai con it nhat 1 liner 500A-compatible trong response
    assert len(codes) > 0, "Filter qua khat — Liner response empty!"


def test_308R_returns_350A_parts():
    """YMSA-308R (350A) van duoc tra TK-308RR nhu cu."""
    result = get_replacement_steps(category="TipBody", torch_model="YMSA-308R")
    codes = _extract_part_codes(result)
    assert "016051" in codes, f"Lost compatibility with 350A torch. Got: {codes}"


def test_no_torch_model_keeps_full_list():
    """Query khong co torch -> tra full unfiltered list."""
    result = get_replacement_steps(category="TipBody")
    codes = _extract_part_codes(result)
    assert len(codes) >= 3, f"Should return full list when no torch context, got: {codes}"


def test_unknown_torch_falls_back_to_unfiltered():
    """Torch khong ton tai -> fallback ve full list (khong crash, khong empty)."""
    result = get_replacement_steps(category="TipBody", torch_model="NONEXISTENT-999")
    codes = _extract_part_codes(result)
    assert len(codes) > 0, "Unknown torch should fall back to unfiltered list"

