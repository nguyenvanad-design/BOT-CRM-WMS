"""
tests/test_replacement_steps_compat.py
========================================
Regression tests cho bug fix Patch #1:
  - YMSA-508R (500A) không được leak TK-308RR (350A) parts vào related_parts
  - YMSA-308R (350A) vẫn nhận đúng parts 350A
  - Query không có torch_model vẫn giữ hành vi cũ (backward compat)

Chạy:
    pytest tests/test_replacement_steps_compat.py -v
    # hoặc chạy 1 test cụ thể:
    pytest tests/test_replacement_steps_compat.py::test_508R_no_350A_parts_leak -v
"""

import pytest
from core.tool_wrappers import get_replacement_steps


def _extract_part_codes(result: dict) -> set:
    """Helper: pull all tokin_part_no from related_parts."""
    assert result.get("success"), f"Tool call failed: {result}"
    parts = result.get("data", {}).get("related_parts", [])
    return {p.get("tokin_part_no") for p in parts if p.get("tokin_part_no")}


# ─── BUG FIX: 500A torch không được lẫn 350A parts ───────────────────────────

def test_508R_no_350A_tip_body_leak():
    """YMSA-508R (500A) → TipBody response phải KHÔNG chứa TK-308RR (350A)."""
    result = get_replacement_steps(category="TipBody", torch_model="YMSA-508R")
    codes = _extract_part_codes(result)

    # PHẢI có: 016403 (TK-508RR, 500A)
    assert "016403" in codes, f"Missing compatible 500A part 016403. Got: {codes}"

    # KHÔNG được có (đây là bug đã xảy ra):
    assert "016051" not in codes, f"BUG: 350A part 016051 (TK-308RR) leaked into 500A response! Got: {codes}"
    assert "016503" not in codes, f"BUG: 350A part 016503 (ACC-308RR) leaked into 500A response! Got: {codes}"


def test_508R_no_350A_liner_leak():
    """YMSA-508R → Liner response không được lẫn liner 308RR (350A)."""
    result = get_replacement_steps(category="Liner", torch_model="YMSA-508R")
    codes = _extract_part_codes(result)

    # 016076, 016126 là liner cho 308RR series (350A) — không phù hợp 500A
    assert "016076" not in codes, f"BUG: 350A liner 016076 leaked for 500A torch. Got: {codes}"
    assert "016126" not in codes, f"BUG: 350A liner 016126 leaked for 500A torch. Got: {codes}"


# ─── REGRESSION: 350A torch vẫn nhận đúng parts ──────────────────────────────

def test_308R_returns_350A_parts():
    """YMSA-308R (350A) vẫn được trả TK-308RR như cũ."""
    result = get_replacement_steps(category="TipBody", torch_model="YMSA-308R")
    codes = _extract_part_codes(result)

    assert "016051" in codes, f"Lost compatibility with 350A torch. Got: {codes}"


# ─── BACKWARD COMPAT: không có torch_model → full list ───────────────────────

def test_no_torch_model_keeps_full_list():
    """Query không có torch → trả full unfiltered list (giữ hành vi cũ)."""
    result = get_replacement_steps(category="TipBody")
    codes = _extract_part_codes(result)

    # Full hardcoded list có 4 mã — chắc chắn >= 3 sau dedup
    assert len(codes) >= 3, f"Should return full list when no torch context, got: {codes}"


# ─── EDGE: unknown torch model → safety fallback ─────────────────────────────

def test_unknown_torch_falls_back_to_unfiltered():
    """Torch model không tồn tại → fallback về full list (không crash, không empty)."""
    result = get_replacement_steps(category="TipBody", torch_model="NONEXISTENT-999")
    codes = _extract_part_codes(result)

    # Should not be empty (safety net activates)
    assert len(codes) > 0, "Unknown torch should fall back to unfiltered list, not empty"


# ─── CC BANDING: 300A torch should accept 350A parts ─────────────────────────

def test_cc_banding_300A_torch_accepts_350A_parts():
    """Torch 300A theo _CC_BAND mapping được accept parts 350A."""
    # Tìm torch 300A trong data — nếu không có thì skip
    from core.data_store import get_data_store
    ds = get_data_store()
    torch_300A = next(
        (name for name, t in ds.torches.items()
         if (t.get("current_class") if isinstance(t, dict) else getattr(t, "current_class", "")) == "300A"),
        None
    )
    if not torch_300A:
        pytest.skip("No 300A torch in test data")

    result = get_replacement_steps(category="Tip", torch_model=torch_300A)
    codes = _extract_part_codes(result)
    # Should have at least some Tip parts (most Tip have current_class=350A)
    assert len(codes) > 0, f"300A torch should accept banded 350A tips. Got: {codes}"
