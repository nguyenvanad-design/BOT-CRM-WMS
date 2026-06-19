# core/vision_module.py
# TOKINARC Vision — Nhận dạng linh kiện từ hình ảnh
# ===================================================
# Gemini Vision phân tích ảnh → suggest mã → hỏi xác nhận → tư vấn tiếp
#
# Flow:
#   1. analyze_image() → VisionResult (part_type, candidates, confidence, condition)
#   2. build_confirm_message() → text hỏi user xác nhận
#   3. build_query() → query string để inject vào pipeline
#
# Confidence routing:
#   ≥ 0.80 → suggest 1 mã, hỏi "đúng không ạ?"
#   0.50–0.79 → show top-3, user chọn
#   < 0.50 → hỏi thêm thông tin
#
# UTF-8 NO BOM

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("tokinarc.vision")

# ── Gemini config ──────────────────────────────────────────────────────────────
GEMINI_KEY   = os.getenv("GEMINI_API_KEY", "")
VISION_MODEL = "gemini-2.5-flash-preview-05-20"  # vision-capable model


# ── VisionResult dataclass ────────────────────────────────────────────────────

@dataclass
class VisionResult:
    """
    Kết quả phân tích ảnh từ Gemini Vision.

    Fields:
        part_type       : loại linh kiện (Tip/Nozzle/Insulator/TipBody/Liner/Orifice/Torch/unknown)
        ecosystem       : hệ N/D/WX/TIG hoặc None nếu không rõ
        condition       : new/worn/damaged/unknown
        candidate_codes : top 1-3 mã Tokin có khả năng nhất (6 số)
        confidence      : 0.0-1.0 — mức độ chắc chắn nhận dạng
        visual_cues     : list mô tả đặc điểm nhận ra được (thread, length, color...)
        confirm_needed  : True nếu cần hỏi user xác nhận trước khi tư vấn
        confirm_msg     : text hỏi xác nhận gửi cho user
        raw_json        : raw Gemini output để debug
    """
    part_type:       str = "unknown"
    ecosystem:       Optional[str] = None
    condition:       str = "unknown"
    candidate_codes: List[str] = field(default_factory=list)
    confidence:      float = 0.0
    visual_cues:     List[str] = field(default_factory=list)
    confirm_needed:  bool = True
    confirm_msg:     str = ""
    raw_json:        dict = field(default_factory=dict)

    # Sau khi user confirm → set confirmed_part_no
    confirmed_part_no: Optional[str] = None

    def to_context_dict(self) -> dict:
        """Convert sang dict để inject vào pipeline entity dict."""
        return {
            "part_nos":            [self.confirmed_part_no] if self.confirmed_part_no
                                   else (self.candidate_codes[:1] if self.confidence >= 0.80 else []),
            "categories":          [self.part_type] if self.part_type != "unknown" else [],
            "ecosystem":           self.ecosystem,
            "_vision_confidence":  self.confidence,
            "_vision_condition":   self.condition,
            "_vision_candidates":  self.candidate_codes,
            "_vision_confirm_needed": self.confirm_needed,
        }


# ── Vision Prompt ─────────────────────────────────────────────────────────────

_VISION_SYSTEM_PROMPT = """\
Bạn là chuyên gia nhận dạng linh kiện súng hàn MIG/MAG/TIG thương hiệu Tokinarc.
Phân tích ảnh và trả về JSON THUẦN TÚY (không markdown, không giải thích ngoài JSON).

OUTPUT SCHEMA:
{
  "part_type": "<Tip|Nozzle|Insulator|TipBody|Liner|Orifice|Torch|WaveWasher|unknown>",
  "ecosystem": "<N|D|WX|TIG|null>",
  "condition": "<new|worn|damaged|unknown>",
  "candidate_codes": ["<6-digit Tokin code>", ...],
  "confidence": <0.0-1.0>,
  "visual_cues": ["<đặc điểm nhận ra>", ...]
}

CÁCH NHẬN BIẾT:

Tip (béc hàn):
  - Hình trụ nhọn, lỗ nhỏ ở đầu cho dây hàn đi qua
  - Màu đồng/vàng (mới), đen/carbon (cũ, mòn)
  - Có ren ở đuôi để vặn vào TipBody
  - Hệ N: ren M6×1.0, dài ~45mm (chuẩn) hoặc ~70mm (dài)
  - Hệ D: ren M6×1.0 nhưng khác pitch, thường ngắn hơn

Nozzle (chụp khí):
  - Hình ống trụ rỗng bên trong, miệng tròn
  - Lắp ngoài cùng của đầu súng
  - Đường kính trong 13/16/19mm
  - Hệ N: đồng hoặc mạ chrome, dài 84-88mm
  - Carbon nozzle: màu đen, dạng ống

Insulator (cách điện):
  - Vòng/ống nhựa màu trắng hoặc đỏ (polymer)
  - Tách Nozzle với TipBody để cách điện
  - Type S: ngắn ~13mm, Type L: dài ~20mm

TipBody (thân giữ béc):
  - Ống đồng hoặc đồng thau, ren trong để vặn Tip
  - Dài hơn Tip, đường kính lớn hơn
  - Phần đuôi lắp vào thân súng

Orifice (sứ chia khí):
  - Vòng sứ/ceramic trắng hoặc xám
  - Có nhiều lỗ nhỏ xung quanh để phân phối khí
  - Mỏng, đường kính ~25-30mm

Liner:
  - Cuộn lò xo dây kim loại hoặc nhựa
  - Dài 1-5m, mềm dẻo
  - Đường kính trong 1.0-3.2mm tùy cỡ dây hàn

Torch (súng hàn):
  - Thân súng hoàn chỉnh hoặc handle
  - Nhận hệ từ connector type hoặc marking

NHẬN CONDITION:
  new     : màu đồng sáng, không carbon, không biến dạng
  worn    : đầu lỗ mòn rộng, carbon đen nhẹ, ren còn ok
  damaged : biến dạng, cháy, ren hỏng, vỡ

NHẬN HỆ:
  Hệ N: connector Panasonic/Yaskawa, ren M6×1.0, màu đồng chuẩn
  Hệ D: connector Daihen/OTC, form factor khác một chút
  Hệ WX: nozzle kim loại dày, water jacket, khác hẳn N/D

CANDIDATE CODES — CHỈ điền nếu nhận ra rõ ràng:
  Tip N 0.9mm 45L: 002001
  Tip N 1.0mm 45L: 002002
  Tip N 1.2mm 45L: 002003
  Tip N 1.6mm 45L: 002004
  Tip N 1.4mm 45L: 002017
  Tip D 1.2mm:     023010
  Nozzle N 500A 88L: 001001, 001005, 001010
  Nozzle N 500A 84L: 001012, 001015
  TipBody N 500A:  016403
  TipBody CS 350A: 036001
  Insulator N S 350A: 004002
  Insulator N L 500A: 004001

Nếu không nhận rõ → confidence thấp, candidate_codes rỗng.
Trả JSON THUẦN TÚY."""


# ── Core functions ─────────────────────────────────────────────────────────────

def extract_image_from_base64(b64_str: str) -> Optional[bytes]:
    """Decode base64 image string → bytes."""
    try:
        # Xử lý data URI prefix: "data:image/jpeg;base64,..."
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        return base64.b64decode(b64_str)
    except Exception as e:
        log.warning(f"[Vision] base64 decode failed: {e}")
        return None


def extract_image_from_url(url: str) -> Optional[bytes]:
    """Download image từ URL → bytes."""
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.read()
    except Exception as e:
        log.warning(f"[Vision] URL fetch failed: {e}")
        return None


def analyze_image(
    image_bytes: bytes,
    user_text: Optional[str] = None,
    gemini_key: Optional[str] = None,
) -> VisionResult:
    """
    Gọi Gemini Vision phân tích ảnh linh kiện.

    Args:
        image_bytes : raw image bytes (JPEG/PNG/WebP)
        user_text   : text user gửi kèm ảnh (nếu có) — dùng để narrow analysis
        gemini_key  : override GEMINI_API_KEY env

    Returns:
        VisionResult với candidates, confidence, condition, confirm_msg
    """
    key = gemini_key or GEMINI_KEY
    if not key:
        log.warning("[Vision] No Gemini API key — returning empty result")
        return _empty_result("Không có API key để phân tích ảnh.")

    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel(VISION_MODEL)

        # Build content parts
        import PIL.Image
        import io
        pil_img = PIL.Image.open(io.BytesIO(image_bytes))

        prompt_parts = [_VISION_SYSTEM_PROMPT]
        if user_text:
            prompt_parts.append(f"\nUser hỏi thêm: {user_text}")
        prompt_parts.append(pil_img)

        response = model.generate_content(
            prompt_parts,
            generation_config={"temperature": 0.1, "max_output_tokens": 512},
        )

        raw_text = response.text or ""
        return _parse_vision_response(raw_text, user_text)

    except Exception as e:
        log.error(f"[Vision] Gemini call failed: {e}")
        return _empty_result(f"Phân tích ảnh gặp lỗi: {type(e).__name__}")


def _parse_vision_response(raw_text: str, user_text: Optional[str] = None) -> VisionResult:
    """Parse Gemini JSON output → VisionResult."""
    try:
        # Strip markdown fences nếu có
        clean = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        data  = json.loads(clean)
    except Exception:
        log.warning(f"[Vision] JSON parse failed: {raw_text[:200]}")
        return _empty_result("Không đọc được kết quả phân tích.")

    part_type = data.get("part_type", "unknown")
    ecosystem = data.get("ecosystem")
    condition = data.get("condition", "unknown")
    candidates = [str(c).zfill(6) for c in (data.get("candidate_codes") or []) if c]
    confidence = float(data.get("confidence", 0.0))
    cues       = data.get("visual_cues") or []

    result = VisionResult(
        part_type       = part_type,
        ecosystem       = ecosystem,
        condition       = condition,
        candidate_codes = candidates[:3],  # max 3
        confidence      = confidence,
        visual_cues     = cues[:5],
        raw_json        = data,
    )

    # Build confirm message theo confidence level
    result.confirm_msg   = build_confirm_message(result, user_text)
    result.confirm_needed = (confidence < 0.95 or not candidates)

    return result


def build_confirm_message(result: VisionResult, user_text: Optional[str] = None) -> str:
    """
    Tạo tin nhắn hỏi xác nhận gửi cho user.

    HIGH (≥0.80): "Em nhận ra đây là béc hàn N 1.2mm — mã 002003. Đúng không ạ?"
    MED (0.50-0.79): "Em thấy có thể là 1 trong 3 loại sau, anh/chị xác nhận:"
    LOW (<0.50): "Em chưa nhận rõ — anh/chị cho biết thêm..."
    """
    _PART_VI = {
        "Tip":       "béc hàn (contact tip)",
        "Nozzle":    "chụp khí (nozzle)",
        "Insulator": "cách điện (insulator)",
        "TipBody":   "thân giữ béc (tip body)",
        "Liner":     "liner (ống dẫn dây)",
        "Orifice":   "sứ chia khí (orifice)",
        "Torch":     "súng hàn",
        "WaveWasher":"vòng đệm lò xo",
        "unknown":   "linh kiện hàn",
    }
    _ECO_VI = {
        "N": "hệ N (Panasonic/Yaskawa)",
        "D": "hệ D (Daihen/OTC)",
        "WX": "hệ WX (water-cooled)",
        "TIG": "TIG",
    }
    _COND_VI = {
        "worn":    "⚠️ Linh kiện có vẻ đã mòn",
        "damaged": "🔴 Linh kiện có dấu hiệu hỏng",
        "new":     "✅ Linh kiện còn mới",
    }

    part_vi = _PART_VI.get(result.part_type, "linh kiện")
    eco_vi  = _ECO_VI.get(result.ecosystem or "", "")
    eco_str = f" {eco_vi}" if eco_vi else ""

    lines = []

    if result.confidence >= 0.80 and result.candidate_codes:
        # HIGH confidence — suggest 1 mã chính
        top_code = result.candidate_codes[0]
        lines.append(f"Em nhận ra đây là **{part_vi}**{eco_str} — mã **{top_code}**.")
        if result.visual_cues:
            cues_str = ", ".join(result.visual_cues[:2])
            lines.append(f"_(Đặc điểm nhận ra: {cues_str})_")
        # Condition warning
        cond_msg = _COND_VI.get(result.condition, "")
        if cond_msg and result.condition != "new":
            lines.append(cond_msg)
        lines.append("\nAnh/chị xác nhận đúng không ạ? 😊")
        if len(result.candidate_codes) > 1:
            alts = " / ".join(result.candidate_codes[1:])
            lines.append(f"_(Hoặc có thể là {alts} — nhắn số để chọn)_")

    elif result.confidence >= 0.50 and result.candidate_codes:
        # MEDIUM confidence — show top-3
        lines.append(f"Em thấy đây có thể là **{part_vi}**{eco_str}.")
        lines.append("Anh/chị xác nhận mã nào đúng ạ:\n")
        for i, code in enumerate(result.candidate_codes[:3], 1):
            lines.append(f"{i}. **{code}**")
        cond_msg = _COND_VI.get(result.condition, "")
        if cond_msg and result.condition != "new":
            lines.append(f"\n{cond_msg} — nên kiểm tra thêm ạ.")
        lines.append("\nNhắn số (1/2/3) hoặc cho biết mã chính xác ạ 😊")

    else:
        # LOW confidence — hỏi thêm
        if result.part_type != "unknown":
            lines.append(f"Em nhận ra đây là **{part_vi}** nhưng chưa rõ mã cụ thể ạ.")
        else:
            lines.append("Ảnh chưa đủ rõ để em nhận dạng linh kiện ạ.")

        if result.visual_cues:
            lines.append(f"_(Đặc điểm thấy được: {', '.join(result.visual_cues[:3])})_")

        questions = []
        if not result.ecosystem:
            questions.append("Anh/chị đang dùng hệ N (Panasonic/Yaskawa) hay hệ D (Daihen/OTC)?")
        if result.part_type == "unknown":
            questions.append("Đây là béc hàn, chụp khí, hay loại linh kiện khác ạ?")
        if not questions:
            questions.append("Anh/chị có thể cho biết thêm thông tin về linh kiện này không ạ?")

        lines.append("\n" + " / ".join(questions) + " 😊")

    return "\n".join(lines)


def build_query(vision_result: VisionResult, user_text: Optional[str] = None) -> Optional[str]:
    """
    Tạo query string để inject vào pipeline từ vision result.

    Chỉ build query khi confidence đủ cao hoặc đã có confirmed_part_no.
    Trả None để pipeline xử lý confirm_msg thay vì query bình thường.
    """
    # Đã có confirmed part → build UPSELL query
    if vision_result.confirmed_part_no:
        return f"{vision_result.confirmed_part_no} cần thêm gì"

    # High confidence + candidate → LOOKUP query
    if vision_result.confidence >= 0.80 and vision_result.candidate_codes:
        top = vision_result.candidate_codes[0]
        return f"{top}"

    # User có text kèm ảnh → kết hợp với part_type
    if user_text and vision_result.part_type != "unknown":
        _PART_Q = {
            "Tip": "béc hàn", "Nozzle": "chụp khí",
            "Insulator": "cách điện", "TipBody": "thân giữ béc",
            "Liner": "liner", "Orifice": "sứ chia khí",
        }
        part_vi = _PART_Q.get(vision_result.part_type, "")
        eco_vi  = {"N": "hệ N", "D": "hệ D", "WX": "hệ WX"}.get(
            vision_result.ecosystem or "", "")
        q = " ".join(filter(None, [part_vi, eco_vi, user_text]))
        return q or None

    # Không đủ info → return None, dùng confirm_msg
    return None


def _empty_result(confirm_msg: str = "") -> VisionResult:
    """Trả VisionResult rỗng khi không phân tích được."""
    return VisionResult(
        part_type="unknown",
        confidence=0.0,
        confirm_needed=True,
        confirm_msg=confirm_msg or "Em chưa phân tích được ảnh. Anh/chị mô tả linh kiện giúp em ạ? 😊",
    )
