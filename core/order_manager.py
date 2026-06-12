"""
order_manager.py — Quản lý đơn hàng TOKINARC / Autoss
Lưu đơn vào logs/orders.jsonl, sẵn sàng push sang CRM sau.
"""
from __future__ import annotations
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("tokinarc.order_manager")

# ── Autoss contact info ───────────────────────────────────────────────────────
AUTOSS_INFO = {
    "name":    "Autoss VN",
    "address": "3/8 Lê Ngung, Phường Tân Tạo, Tp. HCM",
    "phone":   "0909 484 159",
    "email":   "info@autoss.vn",
    "website": "autoss.vn",
}

# ── Slot definitions ──────────────────────────────────────────────────────────
SLOTS = ["ho_ten", "so_dien_thoai", "dia_chi", "email", "zalo"]
SLOT_QUESTIONS = {
    "ho_ten":        "Anh/chị cho em biết họ tên để lên đơn ạ?",
    "so_dien_thoai": "Số điện thoại của anh/chị ạ?",
    "dia_chi":       "Địa chỉ giao hàng của anh/chị ạ?",
    "email":         "Email của anh/chị ạ? (Bỏ qua nếu không có)",
    "zalo":          "Số Zalo của anh/chị có khác số điện thoại không ạ? (Bỏ qua nếu giống)",
}
SKIP_KEYWORDS = ("bỏ qua", "bo qua", "không có", "khong co", "giống", "giong", "skip", "same")

ORDER_DIR = "logs"
ORDER_FILE = os.path.join(ORDER_DIR, "orders.jsonl")
_lock = threading.Lock()
_order_counter: Dict[str, int] = {}  # date → count


def _next_order_id() -> str:
    today = datetime.now().strftime("%Y%m%d")
    with _lock:
        _order_counter[today] = _order_counter.get(today, 0) + 1
        seq = _order_counter[today]
    return f"ORD-{today}-{seq:03d}"


def _save_order(order: dict) -> bool:
    try:
        os.makedirs(ORDER_DIR, exist_ok=True)
        with _lock:
            with open(ORDER_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(order, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        log.error(f"[OrderManager] save failed: {e}")
        return False


# ── OrderState — gắn vào ctx.__dict__ ────────────────────────────────────────

class OrderState:
    """Trạng thái đơn hàng trong 1 session."""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []   # [{part_no, name, qty, unit_price}]
        self.slots: Dict[str, str] = {}         # ho_ten, so_dien_thoai, ...
        self.current_slot: Optional[str] = None
        self.confirmed: bool = False
        self.order_id: Optional[str] = None

    @property
    def next_empty_slot(self) -> Optional[str]:
        for s in SLOTS:
            if s not in self.slots:
                return s
        return None

    @property
    def total(self) -> int:
        return sum(i["qty"] * i["unit_price"] for i in self.items)

    def format_items(self) -> str:
        lines = []
        for i in self.items:
            subtotal = i["qty"] * i["unit_price"]
            lines.append(
                f"  • Mã {i['part_no']} — {i['name']} × {i['qty']} cái"
                f" = {subtotal:,.0f}đ"
            )
        lines.append(f"  ──────────────────────────────")
        lines.append(f"  **Tổng cộng: {self.total:,.0f}đ**")
        return "\n".join(lines)

    def format_confirmation(self) -> str:
        lines = ["📋 **Xác nhận đơn hàng:**", self.format_items(), ""]
        for s in SLOTS:
            val = self.slots.get(s)
            if val:
                label = {
                    "ho_ten": "Họ tên", "so_dien_thoai": "SĐT",
                    "dia_chi": "Địa chỉ", "email": "Email", "zalo": "Zalo",
                }.get(s, s)
                lines.append(f"  {label}: {val}")
        lines += [
            "",
            f"📦 Mã đơn: **{self.order_id}**",
            f"📞 Liên hệ xác nhận: {AUTOSS_INFO['phone']}",
            f"📧 Email: {AUTOSS_INFO['email']}",
            "",
            "✅ Đơn hàng đã ghi nhận! Staff Autoss sẽ liên hệ xác nhận trong vòng 30 phút ạ.",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "order_id":  self.order_id,
            "ts":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "items":     self.items,
            "total_vnd": self.total,
            "customer":  self.slots,
            "company":   AUTOSS_INFO,
        }


# ── Public API ────────────────────────────────────────────────────────────────

def get_or_create_order(ctx) -> OrderState:
    if not hasattr(ctx, "_order_state") or ctx._order_state is None:
        ctx._order_state = OrderState()
    return ctx._order_state


def detect_order_trigger(query: str) -> bool:
    """Khách xác nhận mua / chốt đơn."""
    q = query.lower()
    keywords = (
        "lấy", "lay ", "mua", "đặt hàng", "dat hang", "chốt", "chot",
        "ok lấy", "ok lay", "em lấy", "anh lấy", "tôi lấy", "toi lay",
        "lấy cái", "lay cai", "lấy loại", "lấy mã",
        "đặt", "dat ", "order", "xác nhận đơn", "xac nhan don",
    )
    return any(kw in q for kw in keywords)


def parse_order_from_query(query: str, last_upsell_context: dict) -> Optional[List[dict]]:
    """
    Cố gắng parse mã + số lượng từ query.
    last_upsell_context: {part_no, name, unit_price} từ ctx._last_*
    """
    import re
    items = []

    # Pattern: "lấy 001002, 50 cái" hoặc "50 cái 001002"
    pattern = r'([A-Z0-9]{6,})'
    qty_pattern = r'(\d+)\s*(?:cái|cai|c\b|pcs?)'

    codes = re.findall(pattern, query.upper())
    qty_match = re.search(qty_pattern, query, re.IGNORECASE)
    qty = int(qty_match.group(1)) if qty_match else 1

    if codes:
        for code in codes[:5]:
            items.append({
                "part_no":    code,
                "name":       last_upsell_context.get("name", ""),
                "qty":        qty,
                "unit_price": last_upsell_context.get("unit_price", 0),
            })
    elif last_upsell_context.get("part_no"):
        # Không có mã trong query → dùng context upsell gần nhất
        items.append({
            "part_no":    last_upsell_context["part_no"],
            "name":       last_upsell_context.get("name", ""),
            "qty":        qty,
            "unit_price": last_upsell_context.get("unit_price", 0),
        })

    return items if items else None


def process_slot_answer(state: OrderState, query: str) -> Optional[str]:
    """
    Điền slot hiện tại, trả về câu hỏi slot tiếp theo hoặc None nếu xong.
    """
    if state.current_slot is None:
        return None

    q_lower = query.lower().strip()
    # Cho phép bỏ qua email và zalo
    if state.current_slot in ("email", "zalo") and any(kw in q_lower for kw in SKIP_KEYWORDS):
        pass  # Không ghi slot này
    else:
        state.slots[state.current_slot] = query.strip()

    state.current_slot = None
    next_slot = state.next_empty_slot
    if next_slot:
        state.current_slot = next_slot
        return SLOT_QUESTIONS[next_slot]
    return None  # Xong hết slots


def finalize_order(state: OrderState, ctx) -> str:
    """Tạo order_id, lưu file, trả về confirmation text."""
    state.order_id = _next_order_id()
    state.confirmed = True
    order_dict = state.to_dict()
    _save_order(order_dict)
    log.info(f"[OrderManager] saved {state.order_id} — {len(state.items)} items — {state.total:,}đ")
    # Reset để session có thể tạo đơn mới
    ctx._order_state = None
    return state.format_confirmation()
