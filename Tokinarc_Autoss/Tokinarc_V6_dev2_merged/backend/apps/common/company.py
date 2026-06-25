"""
Tokinarc — apps/common/company.py

Thông tin công ty (bên bán / bên phát hành chứng từ) + logo + đổi số sang chữ.
Dùng chung cho mọi chứng từ xuất ra (Excel / Word). Sửa thông tin công ty ở 1 chỗ.
"""
from __future__ import annotations

import os

COMPANY = {
    'name': 'CÔNG TY TNHH THƯƠNG MẠI DỊCH VỤ AUTOSS',
    'address': '111/28/41 Phạm Văn Chiêu, P. An Hội Tây, TP. Hồ Chí Minh, Việt Nam',
    'showroom': '93/8 Lê Ngung, P. Tân Tạo A, Q. Bình Tân, TP. HCM',
    'tax_code': '0311795422',
    'phone': '0909484159',
    'email': 'info@autoss.vn',
    'website': 'autoss.vn | linhkienrobot.vn',
    'director': 'Trần Phú Nhơn',
    'director_title': 'Giám đốc',
}

_ASSETS = os.path.join(os.path.dirname(__file__), 'assets')


def logo_path() -> str | None:
    """Trả đường dẫn logo nếu có (png ưu tiên, rồi jpg); None nếu chưa đặt logo."""
    for name in ('autoss_logo.png', 'autoss_logo.jpg', 'autoss_logo.jpeg'):
        p = os.path.join(_ASSETS, name)
        if os.path.exists(p):
            return p
    return None


# ─── Đổi số tiền sang chữ tiếng Việt ─────────────────────────────────────────
_DIGITS = ['không', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín']


def _read_three(num: int, full: bool) -> str:
    """Đọc 1 nhóm 3 chữ số. full=True khi không phải nhóm cao nhất (đọc cả 'không trăm')."""
    tram, chuc, donvi = num // 100, (num // 10) % 10, num % 10
    out = []
    if tram > 0 or full:
        out.append(f"{_DIGITS[tram]} trăm")
    if chuc == 0:
        if donvi > 0 and (tram > 0 or full):
            out.append('lẻ')
        if donvi > 0:
            out.append(_DIGITS[donvi])
    elif chuc == 1:
        out.append('mười')
        if donvi == 5:
            out.append('lăm')
        elif donvi > 0:
            out.append(_DIGITS[donvi])
    else:
        out.append(f"{_DIGITS[chuc]} mươi")
        if donvi == 1:
            out.append('mốt')
        elif donvi == 5:
            out.append('lăm')
        elif donvi > 0:
            out.append(_DIGITS[donvi])
    return ' '.join(out)


def vnd_to_words(amount) -> str:
    """Đổi số tiền (VND) sang chữ. VD 150000000 → 'Một trăm năm mươi triệu đồng'."""
    n = int(amount or 0)
    if n == 0:
        return 'Không đồng'
    units = ['', ' nghìn', ' triệu', ' tỷ']
    groups = []
    while n > 0:
        groups.append(n % 1000)
        n //= 1000
    parts = []
    highest = len(groups) - 1
    for i in range(highest, -1, -1):
        if groups[i] == 0:
            continue
        words = _read_three(groups[i], full=(i != highest))
        parts.append(words + units[i])
    text = ' '.join(parts).strip()
    return text[0].upper() + text[1:] + ' đồng'
