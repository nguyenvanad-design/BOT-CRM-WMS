# core/llm_orchestrator_v2.py
# TOKINARC LLM Orchestrator v2 — 2-LLM Architecture
# ====================================================
# LLM 1 (Planner)  : google.genai — function calling, chọn tool, gọi tool
# LLM 2 (Responder): google.genai — nhận history + tool_results → tổng hợp
# + History buffer: inject N turns gần nhất từ SessionContext
# + OUT_OF_SCOPE: detect trước khi gọi Planner → trả lời trực tiếp
#
# Migration: google.generativeai (deprecated) → google.genai
# UTF-8 NO BOM

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("tokinarc.orchestrator_v2")

GEMINI_MODEL         = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY       = os.environ.get("GEMINI_API_KEY", "")
MAX_TOOL_CALLS       = int(os.environ.get("TOKINARC_MAX_TOOL_CALLS", "4"))
PLANNER_TEMP         = 0.0
RESPONDER_TEMP       = 0.3
MAX_OUTPUT_TOKENS    = 1500
HISTORY_INJECT_TURNS = int(os.environ.get("TOKINARC_HISTORY_TURNS", "6"))
# FIX (restructure): budget tổng cho 1 request — planner loop dừng gọi thêm
# tool khi vượt budget, nhảy thẳng sang Responder với data đã có.
REQUEST_BUDGET_S     = float(os.environ.get("TOKINARC_REQUEST_BUDGET_S", "25"))


# ══════════════════════════════════════════════════════════════════════════════
# OUT_OF_SCOPE fast-path
# ══════════════════════════════════════════════════════════════════════════════

_OOS_PAT = re.compile(
    r'\b(xin\s*ch[aà]o|hello|hi\b|h[eê]y\b|ch[aà]o\s*(b[aạ]n|anh|ch[iị]|em)'
    r'|gi[aá]\s*(m[aá]y\s*h[aà]n|thi[eế]t\s*b[iị]|robot\s*h[aà]n|b[iì]nh\s*kh[ií])'
    r'|m[aá]y\s*h[aà]n\s*(gi[aá]|bao\s*nhi[eê]u)'
    r'|giao\s*h[aà]ng|ship\b|v[aậ]n\s*chuy[eể]n'
    r'|thanh\s*to[aá]n|chuy[eể]n\s*kho[aả]n'
    r'|b[aả]o\s*h[aà]nh|warranty'
    r'|t[oồ]n\s*kho|h[aà]ng\s*c[oó]\s*s[aẵ]n'
    r'|th[oờ]i\s*ti[eế]t|b[oó]ng\s*[dđ][aá])\b',
    re.I | re.UNICODE,
)

# FIX (restructure 2026-06): dedupe (bỏ ~30 mục lặp 2-3 lần, tập keyword
# KHÔNG đổi) + chuyển ra module-level để không rebuild list mỗi request.
_DOMAIN_KW = (
    'bec','boc','chup','liner','ong trong','cach dien','than giu','tipbody',
    'tip','nozzle','insulator','orifice','collet','tungsten','inner tube',
    'he n','he d','wx ','tcc ','350a','500a','200a','450a','700a','300a',
    'vat tu','linh kien','tieu hao','bo do','consumable','set vat',
    'liet ke','danh sach','co may loai','bao nhieu loai','hien co','dang ban',
    'co gi','tat ca','model nao','model sung',
    'thay the nao','buoc nao','quy trinh','huong dan','luc siet','torque',
    'lap liner','thay chup','thay bec','thao lap','lap dung',
    'ban bi','ban toa','spatter','ro khi','ket day','chay bec',
    'mo han xau','ho quang','khi khong ra','day ra khong deu',
    'sung bi','bi ro','rong khi','toa lua',
    'day cuon','cuon trong','liner bi','chay nhanh','bec den','nam den',
    'ra khong deu','khong ra','bi hong','bi dut','bi chay','bi ket','bi tuot',
    'khong on dinh','ho quang nhay','bi loi','gap su co',
    'duoc khong','tuong thich','lap duoc','dung chung','fit vao',
    'khac gi','khac nhau','tot hon','ben hon','so sanh','vs ',
    'tim mua','can mua','mua ','gia ','sung ','robot ',
    'ong lot','day dan','cup ','chup ','bec ',
    'liet ke set','cac set','set hien','hay ',
    'thi tot','cai nao tot','chon cai','phan biet',
    'back cap','backcap','ceramic','vonfram','dien cuc',
    'tig ','kep dien','innertube',
    'tip adapter','liner oring','o-ring','wave washer',
    'insulation','nozzle sleeve','nozzle nut','wx center',
    'wx702','wx500','tl-20','tla-20','a-350r',
    'dat mua','mua hang','mua 10','mua 100','so luong',
    'electrode','nap duoi','nap hau','cap hau',
    'ymxa','ymsa','tk-308','tk-508','acc-308',
    'wx451','wx452','csl',
    'yt-','tcc-','srct-','dsrc-',
    'von fram',
    'mua them','order',
    'chup su','chup sao','gom',
    'ong dan',
    'o ring',
)


def _detect_oos(query: str) -> Optional[str]:
    q = query.lower().strip()
    if not q or len(q) < 3:
        return "Dạ chào anh/chị! Em là trợ lý tư vấn kỹ thuật linh kiện súng hàn Tokinarc của Autoss. Anh/chị cần tư vấn gì ạ?"
    if re.match(r'^(hi|hello|hey|ch[aà]o|xin\s*ch[aà]o|alo)\s*[!.]*\s*$', q, re.I | re.UNICODE):
        return "Dạ chào anh/chị! Em là trợ lý tư vấn kỹ thuật linh kiện súng hàn Tokinarc của Autoss. Anh/chị cần tư vấn gì ạ?"
    if any(k in q for k in _DOMAIN_KW):
        return None
    m = _OOS_PAT.search(q)
    if not m:
        return None
    t = m.group(0).lower()
    if any(k in t for k in ('máy hàn','robot hàn','bình khí','thiết bị')):
        return "Dạ giá máy hàn/thiết bị anh/chị vui lòng liên hệ trực tiếp Autoss ạ. Em chỉ tư vấn linh kiện và vật tư tiêu hao súng hàn Tokinarc."
    if any(k in t for k in ('giao hàng','ship','vận chuyển')):
        return "Dạ thông tin giao hàng anh/chị vui lòng liên hệ trực tiếp bộ phận kinh doanh Autoss ạ."
    if any(k in t for k in ('thanh toán','chuyển khoản')):
        return "Dạ thông tin thanh toán anh/chị vui lòng liên hệ trực tiếp Autoss ạ."
    if any(k in t for k in ('bảo hành','warranty')):
        return "Dạ thông tin bảo hành anh/chị vui lòng liên hệ trực tiếp Autoss ạ."
    if any(k in t for k in ('tồn kho','có sẵn')):
        return "Dạ tình trạng tồn kho anh/chị vui lòng liên hệ trực tiếp Autoss để kiểm tra ạ."
    if any(k in t for k in ('xin chào','hello','hi','hey','chào')):
        return "Dạ chào anh/chị! Anh/chị cần tư vấn linh kiện súng hàn Tokinarc gì ạ?"
    return "Dạ câu hỏi này nằm ngoài phạm vi tư vấn kỹ thuật của em. Anh/chị cần tư vấn về linh kiện súng hàn Tokinarc không ạ?"


# ══════════════════════════════════════════════════════════════════════════════
# Sanitizer
# ══════════════════════════════════════════════════════════════════════════════

def _to_python(obj: Any) -> Any:
    if obj is None: return None
    if isinstance(obj, bool): return obj
    if isinstance(obj, (int, float)): return obj
    if isinstance(obj, str): return obj
    if isinstance(obj, dict): return {str(k): _to_python(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)): return [_to_python(i) for i in obj]
    nm = getattr(type(obj), "__module__", "")
    tn = type(obj).__name__
    if "proto" in nm or "protobuf" in nm or tn in (
        "MapComposite","RepeatedComposite","MessageMapContainer",
        "ScalarMapContainer","RepeatedScalarFieldContainer","RepeatedCompositeFieldContainer",
    ):
        try: return {str(k): _to_python(v) for k, v in dict(obj).items()}
        except Exception: pass
        try: return [_to_python(i) for i in list(obj)]
        except Exception: pass
    if hasattr(obj,"__iter__") and not isinstance(obj,(str,bytes)):
        try: return [_to_python(i) for i in obj]
        except Exception: pass
    try: return str(obj)
    except Exception: return ""


def _sanitize(obj: Any, _d: int = 0) -> Any:
    obj = _to_python(obj)
    if _d > 6: return str(obj)[:200]
    if obj is None: return ""
    if isinstance(obj, bool): return obj
    if isinstance(obj, (int, float)): return obj
    if isinstance(obj, str): return obj[:2000]
    if isinstance(obj, list):
        lim = 50 if _d <= 3 else max(10, 30 - _d * 3)
        return [_sanitize(i, _d+1) for i in obj[:lim]]
    if isinstance(obj, dict):
        return {str(k): _sanitize(v, _d+1) for k, v in obj.items()
                if v is not None
                and not (isinstance(v,(list,dict)) and len(v)==0)
                and not str(k).startswith("_")}
    try: return str(obj)[:500]
    except Exception: return ""


# ══════════════════════════════════════════════════════════════════════════════
# Response dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class OrchestratorResponse:
    text:           str
    tools_called:   List[str]  = field(default_factory=list)
    tool_results:   List[dict] = field(default_factory=list)
    intent:         str        = ""
    entities:       dict       = field(default_factory=dict)
    success:        bool       = True
    error:          str        = ""
    latency_ms:     int        = 0
    model:          str        = ""

    @property
    def response_text(self) -> str:
        return self.text

    def to_dict(self) -> dict:
        return {"text": self.text, "tools_called": self.tools_called,
                "intent": self.intent, "success": self.success,
                "error": self.error, "latency_ms": self.latency_ms}


# ══════════════════════════════════════════════════════════════════════════════
# Error helpers
# ══════════════════════════════════════════════════════════════════════════════

def _classify_error(exc: Exception) -> Tuple[str, str]:
    s = str(exc).lower()
    if any(k in s for k in ("429","rate_limit","resource_exhausted","quota")):
        return "RATE_LIMIT","Dạ hệ thống đang nhận quá nhiều yêu cầu. Anh/chị vui lòng chờ 30 giây rồi thử lại ạ."
    if any(k in s for k in ("timeout","timed out","deadline")):
        return "TIMEOUT","Dạ phản hồi từ AI mất quá lâu. Anh/chị vui lòng thử lại với câu hỏi ngắn gọn hơn ạ."
    if any(k in s for k in ("503","502","504","unavailable")):
        return "UNAVAILABLE","Dạ dịch vụ AI tạm thời gián đoạn. Anh/chị vui lòng thử lại sau vài phút ạ."
    return "UNKNOWN","Dạ em xin lỗi, hệ thống đang gặp sự cố kỹ thuật. Anh/chị vui lòng thử lại sau ít phút ạ."


def _error_response(exc, tools_called, tool_results, t0, model, prefix="Orch"):
    err_type, vi_msg = _classify_error(exc)
    latency_ms = int((time.time()-t0)*1000)
    log.error(f"[{prefix}] {err_type}: {exc} ({latency_ms}ms)")
    return OrchestratorResponse(
        text=vi_msg, tools_called=tools_called, tool_results=tool_results,
        intent="error", success=False, error=f"{err_type}:{exc}",
        latency_ms=latency_ms, model=model,
    )


# ══════════════════════════════════════════════════════════════════════════════
# History builder
# ══════════════════════════════════════════════════════════════════════════════

def _build_history(ctx, client_history: Optional[List[dict]]) -> List[dict]:
    if client_history:
        return list(client_history)
    if ctx is None:
        return []
    if hasattr(ctx, "get_history_for_llm"):
        msgs = ctx.get_history_for_llm(max_turns=HISTORY_INJECT_TURNS)
        summary = getattr(ctx, "get_summary_hint", lambda: "")() 
        if summary:
            msgs.insert(0, {"role": "user", "parts": [{"text": summary}]})
            msgs.insert(1, {"role": "model", "parts": [{"text": "Da ghi nhan lich su truoc do."}]})
        if msgs:
            log.debug(f"[Orch] history {len(msgs)//2} turns (cycle={getattr(ctx,'history_cycle',0)})")
            return msgs
    last_q = getattr(ctx,"last_query","") or ""
    last_r = getattr(ctx,"last_text","") or ""
    if last_q and last_r:
        return [{"role":"user","parts":[{"text":last_q}]},
                {"role":"model","parts":[{"text":last_r}]}]
    return []


# ══════════════════════════════════════════════════════════════════════════════
# Responder prompt
# ══════════════════════════════════════════════════════════════════════════════

_RESPONDER_SYSTEM = """\
Bạn là trợ lý tư vấn kỹ thuật Autoss — nhà phân phối Tokinarc tại Việt Nam.
Nhiệm vụ: tổng hợp kết quả tool calls thành câu trả lời tiếng Việt tự nhiên, chính xác.

QUY TẮC CỨNG — KHÔNG NGOẠI LỆ:
1. CHỈ dùng data từ tool_results — KHÔNG tự bịa mã part, giá, spec.
2. Mọi part PHẢI có mã Tokin 6 số: "Mã 002001 — Béc hàn N 0.9mm — 18.000đ/cái".
   TUYỆT ĐỐI không đề cập part mà không có mã. Không được bỏ sót mã nào.
2b. THƯƠNG HIỆU TOKINARC (BẮT BUỘC) — Câu MỞ ĐẦU khi liệt kê/báo giá sản phẩm
   PHẢI có chữ "Tokinarc" (Autoss phân phối ĐỘC QUYỀN Tokinarc tại VN).
   ✅ "em gửi thông tin các loại béc hàn Tokinarc 1.2mm hệ N ạ:"
   ✅ "các mẫu chụp khí Tokinarc 500A bên em gồm:"
   ❌ "em gửi thông tin các loại béc hàn 1.2mm hệ N" (THIẾU thương hiệu — KHÔNG được).
   Chỉ cần nêu "Tokinarc" 1 lần ở câu mở đầu, không lặp ở từng dòng mã.
3. Xưng "em", gọi "anh/chị".
4. tool_results rỗng hoặc success=false → thông báo không tìm thấy, gợi ý hỏi lại.
   NGOẠI LỆ [get_torches] NO_TORCHES_FOUND: KHÔNG nói "không tìm thấy".
   Dùng domain knowledge trả model phổ biến + hỏi qualify:
   Robot MA1440/1.4m → "TK-308RR (350A), YMXA-308R, YMSA-308R (cảm biến), TK-508RR (500A)..."
   Yaskawa chung → nhóm theo MA/MH, hỏi công suất + loại cáp.
   TUYỆT ĐỐI KHÔNG xin lỗi hoặc hỏi "anh/chị cho em mã cụ thể".
5. [get_torches] success=true: KHÔNG liệt kê hết toàn bộ — chỉ nêu đại diện mỗi nhóm rồi hỏi qualify:
   • Cáp ngoài (MH): TK-308RR/508RR, ACC-308RR, SRCT-308R
   • Cáp trong (MA): YMXA-308R (không cảm biến), YMSA-308R (có cảm biến)
   • Nước: TK-308RW, YMSA-500W
   → Hỏi: "Anh/chị hàn dây cỡ mấy mm và cần cảm biến chống va đập không?"
   Sau khi khách trả lời → báo giá + spec model cụ thể.
6. CONSUMABLE_SET: liệt kê ĐỦ 6 nhóm TipBody→Tip→Nozzle→Insulator→Orifice→Liner.
   TUYỆT ĐỐI KHÔNG dừng lại ở 1-2 nhóm rồi hỏi — in ĐỦ 6 nhóm trước.
6. Nếu tool_results chỉ có mã số mà KHÔNG có tên → vẫn liệt kê đầy đủ mã, ghi "(xem catalog)".
7. KHÔNG rút gọn danh sách — in TOÀN BỘ parts có trong tool_results.
8. find_upsell_companions trả về nhiều parts → liệt kê theo nhóm category, KHÔNG bỏ bớt.
9. Liner KHÔNG có trong consumable_set → cuối response thêm: "Về dây dẫn hướng (Liner): anh/chị cho em biết model súng hàn (VD: TK-308RR, TK-508RR) và chiều dài cáp để em tư vấn đúng ạ."
10. Cuối response hỏi 1 câu qualify (trừ khi đã đủ info).
11. LEAD — XỬ LÝ KẾT QUẢ capture_lead:
    • saved=false / need_more_info=true → KHÔNG nói "đã lưu/sẽ liên hệ". NĂN NỈ ĐÚNG 1 LẦN
      xin Họ tên + Công ty + Địa chỉ (MST nếu có), giọng dễ thương, hơi tội nghiệp:
      "Dạ em cảm ơn ạ! Anh/chị cho em xin thêm họ tên, tên công ty và địa chỉ với ạ,
       không sếp lại nhắc em huhu 🙏 — để em lên đơn cho anh/chị được giá tốt nhất."
      → Đây là năn nỉ DUY NHẤT. Nếu lượt SAU khách vẫn không cho thêm/từ chối, hệ thống
        sẽ tự lưu bằng SĐT (không năn nỉ lần 2).
    • saved=true → "Em đã ghi nhận thông tin, bộ phận kinh doanh sẽ GỌI NGAY cho anh/chị ạ.
      Em cảm ơn anh/chị!"  (KHÔNG nói "trong 30 phút").

QUY TẮC IN MÃ THEO INTENT:

[SEARCH_BY_DESC] tool_results có parts → PHẢI in MÃ của TỪNG part:
  - Có kết quả → liệt kê ngay, KHÔNG hỏi lại hệ/dòng điện trước
  - Format: "Mã XXXXXX — Tên — XXX.XXXđ/cái"
  - Hỏi qualify SAU KHI đã liệt kê xong

[REPAIR / get_troubleshoot] → PHẢI có mục "Linh kiện cần kiểm tra/thay:":
  - Liệt kê ĐẦY ĐỦ mã từ related_parts trong tool_results
  - Format bắt buộc: "Mã XXXXXX — Tên linh kiện"
  - KHÔNG được kết thúc response mà không có mã part nào

[INSTALLATION / get_replacement_steps] → Sau các bước, PHẢI có mục "Linh kiện liên quan:":
  - Liệt kê mã parts từ related_parts trong tool_results
  - Format: "Mã XXXXXX — Tên"
  - Nếu related_parts rỗng → dùng _CATEGORY_PARTS mặc định theo category

[UPSELL / find_upsell_companions] → liệt kê companions theo nhóm:
  - Mỗi nhóm: "**[Tên nhóm]:** Mã XXXXXX — Tên — Giá"
  - PHẢI in mã của TỪNG companion, không được bỏ sót

[COMPARISON / compare_parts] → format bảng:
  - Dòng đầu: "So sánh Mã XXXXXX vs Mã YYYYYY:"
  - PHẢI in cả 2 mã đã resolve (không dùng alias đầu vào)

[CONSUMABLE_SET fallback] → khi không có exact match:
  - Vẫn in kết quả gần nhất + note "Em dùng bộ [XXX] tương đương gần nhất"
  - KHÔNG báo lỗi hoặc hỏi lại khi đã có fallback data
"""

_SYNTHESIS_RULES = (
    "\n\n=== SYNTHESIS RULES ===\n"
    "1. Chỉ dùng data từ tool results bên dưới.\n"
    "2. Nếu có warnings → nêu rõ.\n"
    "3. CONSUMABLE_SET: in ĐỦ 6 nhóm trước khi hỏi thêm.\n"
    "4. Liệt kê đầy đủ, không bỏ sót part.\n"
    "5. Giá format: XX.XXXđ/cái — LUÔN có giá, không được bỏ trống.\n"
    "6. MỖI part PHẢI có mã (6 số Tokin). Không được bỏ sót mã.\n"
    "7. COMPARISON: trình bày dạng bảng so sánh spec từng cột.\n"
    "8. UPSELL: nhóm theo category (Tip / Nozzle / Insulator...).\n"
    "9. Nếu tool_summary có ecosystem và current_class → KHÔNG hỏi lại hệ hay dòng điện.\n"
    "10. KHÔNG hỏi loại khí bảo vệ khi tư vấn part.\n"
    "11. Khi khách hỏi 'liệt kê tiếp' / 'còn gì nữa' / 'thêm nữa': "
    "gọi find_upsell_companions(part_no=X, page=2) → page=3 → ... "
    "Khi has_more=false VÀ companions rỗng (hết sản phẩm): "
    "→ 'Anh/chị ơi, em đã liệt kê hết [tên category] tương thích rồi ạ. "
    "Anh/chị muốn xem thêm loại linh kiện khác (cách điện, thân giữ béc, sứ chia khí...) không?' "
    "KHÔNG nói 'không tìm thấy' hay 'không có thêm' — gợi ý category khác.\n"
    "Khi has_more=false VÀ companions có data (trang cuối có hàng): "
    "→ 'Đây là toàn bộ X loại [category] tương thích ạ.' + gợi ý mua hoặc hỏi linh kiện khác.\n"
    "Khi has_more=true: KHÔNG nói 'đây là toàn bộ' — còn có thể liệt kê tiếp.\n"
    "12. Khi query chỉ hỏi 1 loại linh kiện cụ thể ('cần thêm chụp khí', 'cần béc', 'thân giữ béc'): "
    "gọi find_upsell_companions với include_categories=['Nozzle'] / ['Tip'] / ['TipBody'] / ['Insulator']. "
    "CHỈ hiển thị loại đó — không list thêm các loại khác.\n"
    "13. Giá trong page 2+ (compatible_with): lấy từ field price_vnd trong companions. "
    "KHÔNG bỏ trống giá dù part ở bất kỳ page nào.\n"
    "========================\n"
)


_PART_KEEP = {"tokin_part_no","display_name_vi","price_vnd","category","ecosystem","current_class","wire_size_mm","is_priority_sell","p_part_nos","d_part_nos"}

def _compact_part(p):
    if not isinstance(p, dict): return p
    return {k: v for k, v in p.items() if k in _PART_KEEP and v is not None}

def _compact_result(tool_name, result):
    if not isinstance(result, dict): return result
    inner  = result.get("result", result)
    success = inner.get("success", result.get("success", False))
    reason  = inner.get("reason",  result.get("reason", ""))
    data    = inner.get("data",    result.get("data"))
    out = {"success": success}
    if reason: out["reason"] = reason
    if not success or data is None: return out
    if tool_name in ("search_parts", "find_upsell_companions"):
        parts = data.get("parts") or data.get("companions") or data.get("items") or []
        out["data"] = {"total": data.get("total", len(parts)), "parts": [_compact_part(p) for p in parts[:20]]}
    elif tool_name == "lookup_part":
        out["data"] = _compact_part(data) if isinstance(data, dict) else data
    elif tool_name == "get_consumable_set":
        parts = data.get("parts") or data.get("items") or []
        out["data"] = {k: v for k, v in data.items() if k not in ("parts","items")}
        out["data"]["parts"] = [_compact_part(p) for p in parts]
    elif tool_name == "get_torches":
        torches = data.get("torches") or []
        _TORCH_KEEP = {"model_code","display_name_vi","ecosystem","current_class",
                       "torch_type","cooling","rated_a","wire_display","wire_kind",
                       "price_vnd","is_contact_price","shock_sensor_type",
                       "robot_compatibility","robot_series"}
        def _ct(t):
            slim = {k: v for k, v in t.items() if k in _TORCH_KEEP and v is not None}
            rc = slim.get("robot_compatibility")
            if isinstance(rc, list) and len(rc) > 4:
                slim["robot_compatibility"] = rc[:4]
            return slim
        out["data"] = {
            "total":   data.get("total", len(torches)),
            "torches": [_ct(t) for t in torches[:50]],
        }
        if data.get("retry_dropped"):
            out["data"]["retry_dropped"] = data["retry_dropped"]
        if data.get("filters_applied"):
            out["data"]["filters_applied"] = data["filters_applied"]
    else:
        out["data"] = data
    return out

def build_tool_summary(tool_results):
    import json as _j
    compacted = [{"tool": r["tool"], "result": _compact_result(r["tool"], r.get("result", {}))} for r in tool_results]
    try:
        summary = _j.dumps(compacted, ensure_ascii=False)
        if len(summary) > 12000:
            for item in compacted:
                d = item["result"].get("data", {})
                for key in ("parts","companions"):
                    if isinstance(d.get(key), list) and len(d[key]) > 10:
                        d[key] = d[key][:10]
            summary = _j.dumps(compacted, ensure_ascii=False)
        return summary
    except Exception:
        return _j.dumps([{"tool": r["tool"], "result": {"success": False}} for r in tool_results])


# Category keyword → include_categories mapping
_CATEGORY_KEYWORDS = {
    "Nozzle":    ["chụp khí", "chup khi", "cup khi", "nozzle", "chụp", "cup", "ly",
                  "ceramic nozzle", "chụp sứ", "chup su"],
    "Tip":       ["béc hàn", "bec han", "béc", "bec", "tip", "đầu tiếp điện", "dau tiep dien",
                  "contact tip", "tiếp điện", "tiep dien"],
    "TipBody":   ["thân giữ béc", "than giu bec", "tip body", "tipbody", "thân béc",
                  "than bec", "giữ béc", "giu bec"],
    "Insulator": ["cách điện", "cach dien", "insulator", "vỏ cách điện", "vo cach dien"],
    "Orifice":   ["sứ chia khí", "su chia khi", "orifice", "diffuser", "khuếch tán"],
    "Liner":     ["liner", "ống trong", "ong trong", "dây dẫn hướng", "day dan huong",
                  "ống lót", "ong lot", "inner tube"],
}

def _detect_category_from_query(query: str) -> list:
    """Detect category LLM nên filter khi user chỉ hỏi 1 loại."""
    q = query.lower()
    found = []
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            found.append(cat)
    # Chỉ return nếu tìm thấy ĐÚNG 1 category — nhiều hơn thì không filter
    return found if len(found) == 1 else []


# FIX (restructure 2026-06): các keyword list + map này trước đây bị copy
# 2-3 bản trong run()/stream_response() — gom về module-level dùng chung.
_PAGINATION_KW = ("liệt kê tiếp", "liet ke tiep", "còn nữa", "con nua",
                  "còn loại nào", "con loai nao", "xem thêm", "xem them",
                  "thêm nữa", "them nua", "còn gì", "con gi", "tiếp theo",
                  "tiep theo", "page 2", "trang 2")

_UPSELL_KW = ("bec", "than gi", "cach dien", "di kem", "can them",
              "tu van", "linh kien", "béc", "thân giữ",
              "cách điện", "đi kèm", "cần thêm",
              "tư vấn", "linh kiện", "vật tư", "vat tu",
              "tiêu hao", "tieu hao", "sử dụng với", "dùng với")

# Map keyword trong assistant text → category name (dùng cho pagination lock)
_CAT_KEYWORD_MAP = {
    "chụp khí": "Nozzle", "nozzle": "Nozzle",
    "béc hàn": "Tip", "tip ": "Tip",
    "thân giữ béc": "TipBody", "tip body": "TipBody",
    "cách điện": "Insulator", "insulator": "Insulator",
    "sứ chia khí": "Orifice", "orifice": "Orifice",
    "liner": "Liner", "ống lót dây": "Liner",
    "back cap": "BackCap", "nắp sau": "BackCap",
}


def _is_pagination_query(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in _PAGINATION_KW)


def _needs_upsell_query(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in _UPSELL_KW)


def _build_context_hint(tool_results: list) -> str:
    """
    Tự động extract ecosystem + current_class từ lookup_part result.
    Inject vào responder_prompt để LLM2 không hỏi lại.
    """
    import json as _json
    for r in tool_results:
        if r.get("tool") != "lookup_part":
            continue
        result = r.get("result", {})
        data = result.get("data") or result.get("result", {}).get("data")
        if not isinstance(data, dict):
            continue
        eco = data.get("ecosystem", "")
        cc  = data.get("current_class", "")
        pno = data.get("tokin_part_no", "")
        cat = data.get("category", "")
        if eco and eco not in ("", "UNKNOWN") and cc:
            hint = (
                f"\n[CONTEXT ĐÃ BIẾT từ lookup] Mã {pno} ({cat}): "
                f"ecosystem={eco}, current_class={cc}. "
                f"KHÔNG hỏi lại hệ hay dòng điện — dùng ngay để tư vấn.\n"
            )
            return hint
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# Session extract helper (dùng chung)
# ══════════════════════════════════════════════════════════════════════════════

def _extract_session_data(tools_called, tool_results, query):
    INTENT_MAP = {
        "lookup_part":"LOOKUP","search_parts":"SEARCH_BY_DESC",
        "get_consumable_set":"CONSUMABLE_SET","find_upsell_companions":"UPSELL",
        "find_replacement":"REPLACEMENT","check_compatibility":"COMPATIBILITY_CHECK",
        "compare_parts":"COMPARISON","get_torches":"AGGREGATE",
        "get_troubleshoot":"REPAIR","get_replacement_steps":"INSTALLATION",
        "get_liner_length":"INSTALLATION",
    }
    intent = next((INTENT_MAP[t] for t in tools_called if t in INTENT_MAP), "OUT_OF_SCOPE")
    entities: dict = {}
    returned: list = []

    for tr in tool_results:
        args   = tr.get("args", {})
        result = tr.get("result", {})
        if "part_no" in args:
            entities.setdefault("part_nos",[])
            if args["part_no"] not in entities["part_nos"]:
                entities["part_nos"].append(args["part_no"])
        if args.get("ecosystem"):     entities["ecosystem"]     = args["ecosystem"]
        if args.get("current_class"): entities["current_class"] = args["current_class"]
        if args.get("torch_model"):
            entities.setdefault("torch_models",[])
            if args["torch_model"] not in entities["torch_models"]:
                entities["torch_models"].append(args["torch_model"])

        _raw  = result.get("result", result)
        _ok   = _raw.get("success", result.get("success", False))
        _data = _raw.get("data", result.get("data"))
        if _ok and isinstance(_data, dict):
            if _data.get("tokin_part_no"):
                returned.append({"tokin_part_no": _data["tokin_part_no"]})
            for key in ("companions","parts","items","related_parts"):
                for p in (_data.get(key) or [])[:60]:
                    if isinstance(p,dict):
                        pno = p.get("tokin_part_no") or p.get("part_id") or p.get("part_no","")
                        if pno: returned.append({"tokin_part_no":pno})
            # consumable_sets dùng key "items" với field "part_id"
            for cs in (_data.get("sets") or _data.get("consumable_sets") or []):
                for p in (cs.get("parts") or cs.get("items") or [])[:30]:
                    if isinstance(p, dict):
                        pno = p.get("tokin_part_no") or p.get("part_id") or p.get("part_no", "")
                        if pno: returned.append({"tokin_part_no": pno})
            if _data.get("model_code") and not _data.get("tokin_part_no"):
                returned.append({"tokin_part_no":_data["model_code"]})
        elif _ok and isinstance(_data, list):
            for p in _data[:60]:
                if isinstance(p,dict):
                    pno = p.get("tokin_part_no") or p.get("part_id","")
                    if pno: returned.append({"tokin_part_no":pno})

    seen: set = set()
    deduped = []
    for p in returned:
        pno = p.get("tokin_part_no","")
        if pno and pno not in seen:
            seen.add(pno); deduped.append(p)
    return intent, entities, deduped[:10]


# ══════════════════════════════════════════════════════════════════════════════
# OrchestratorV2 — SDK (google.genai)
# ══════════════════════════════════════════════════════════════════════════════

class OrchestratorV2:

    def __init__(self, api_key: str = GEMINI_API_KEY, model: str = GEMINI_MODEL):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY","")
        self.model   = model
        self._client = None
        from core.system_prompts import ASSISTANT_PROMPT, TOOL_SCHEMA
        self._planner_system = ASSISTANT_PROMPT
        self._tool_schema    = TOOL_SCHEMA
        self._gemini_tools   = None
        from core.session_store import get_session_store
        self._ss = get_session_store()
        from core.tool_wrappers import dispatch as _dispatch
        self._dispatch = _dispatch
        log.info(f"[OrchestratorV2] init model={self.model} (google.genai)")

    def _get_client(self):
        if self._client is None:
            import google.genai as genai
            self._client = genai.Client(api_key=self.api_key)
            log.info("[OrchestratorV2] google.genai client initialized")
        return self._client

    def _get_tools(self):
        if self._gemini_tools is None:
            import google.genai.types as gt
            decls = [
                gt.FunctionDeclaration(
                    name=t["name"], description=t["description"],
                    parameters=t.get("parameters",{}),
                )
                for t in self._tool_schema
            ]
            self._gemini_tools = [gt.Tool(function_declarations=decls)]
        return self._gemini_tools

    def run(self, query: str, session_id=None, history=None,
            image_data=None, image_mime="image/jpeg") -> OrchestratorResponse:
        t0 = time.time()

        if not query and not image_data:
            return OrchestratorResponse(text="Dạ anh/chị cần tư vấn gì ạ?",
                                        success=True, latency_ms=0, model=self.model)

        # OUT_OF_SCOPE fast-path
        if not image_data:
            oos = _detect_oos(query)
            if oos:
                log.info(f"[OrchestratorV2] OOS: {query[:50]!r}")
                ctx = self._ss.get_or_create(session_id)
                if ctx:
                    self._ss.update(ctx,"OUT_OF_SCOPE",{},[],query=query,response_text=oos)
                return OrchestratorResponse(text=oos, intent="OUT_OF_SCOPE",
                    success=True, latency_ms=int((time.time()-t0)*1000), model="oos_fast_path")

        ctx = self._ss.get_or_create(session_id)
        base_history = _build_history(ctx, history)

        import google.genai.types as gt

        user_parts = []
        if image_data:
            user_parts.append(gt.Part.from_bytes(data=image_data, mime_type=image_mime))
        user_parts.append(gt.Part.from_text(text=query))

        # Convert history dicts → Content objects
        def _to_content(m):
            if hasattr(m,"role"): return m
            role  = m.get("role","user")
            parts_raw = m.get("parts",[])
            parts_obj = []
            for p in parts_raw:
                if isinstance(p, str): parts_obj.append(gt.Part.from_text(text=p))
                elif isinstance(p, dict) and "text" in p: parts_obj.append(gt.Part.from_text(text=p["text"]))
                else: parts_obj.append(p)
            return gt.Content(role=role, parts=parts_obj)

        current = [_to_content(m) for m in base_history]
        current.append(gt.Content(role="user", parts=user_parts))

        tools_called: List[str]  = []
        tool_results: List[dict] = []
        tool_call_count = 0

        try:
            client = self._get_client()
            planner_cfg = gt.GenerateContentConfig(
                system_instruction = self._planner_system,
                tools              = self._get_tools(),
                tool_config        = gt.ToolConfig(
                    function_calling_config=gt.FunctionCallingConfig(
                        mode=gt.FunctionCallingConfig.Mode.ANY,
                    )
                ),
                temperature        = PLANNER_TEMP,
                max_output_tokens  = MAX_OUTPUT_TOKENS,
                thinking_config    = gt.ThinkingConfig(thinking_budget=0),
            )

            # ── LLM 1: Planner ────────────────────────────────────────────────
            while tool_call_count <= MAX_TOOL_CALLS:
                log.info(f"[Planner] call #{tool_call_count+1} msgs={len(current)}")
                resp = client.models.generate_content(
                    model=self.model, contents=current, config=planner_cfg,
                )
                cand = resp.candidates[0] if resp.candidates else None
                if not cand or not cand.content:
                    break

                parts    = cand.content.parts or []
                fc_parts = [p for p in parts if p.function_call and p.function_call.name]

                if not fc_parts:
                    current.append(cand.content)
                    break
                if tool_call_count >= MAX_TOOL_CALLS:
                    log.warning(f"[Planner] MAX_TOOL_CALLS reached")
                    current.append(cand.content)
                    break

                current.append(cand.content)

                fn_resps = []
                for fc in fc_parts:
                    fn_name = fc.function_call.name
                    fn_args = _to_python(dict(fc.function_call.args or {}))
                    log.info(f"[Planner] tool: {fn_name}({list(fn_args.keys())})")
                    tools_called.append(fn_name)
                    t_tool = time.time()
                    try:
                        result = self._dispatch(fn_name, fn_args)
                    except Exception as e:
                        log.error(f"[Planner] {fn_name} error: {e}")
                        result = {"success":False,"reason":str(e)}
                    safe = _sanitize(result)
                    tool_results.append({"tool":fn_name,"args":fn_args,"result":safe})
                    log.info(f"[Planner] {fn_name} done {int((time.time()-t_tool)*1000)}ms")
                    fn_resps.append(gt.Part.from_function_response(name=fn_name, response=safe))

                current.append(gt.Content(role="user", parts=fn_resps))
                tool_call_count += 1
                # FAST-STOP: tool thanh cong → skip Planner confirm turn
                all_success = all(
                    (tr.get("result") or {}).get("success", False)
                    for tr in tool_results
                )

                # AUTO-INJECT: nếu lookup_part thành công + query có upsell intent
                # → tự động gọi find_upsell_companions mà không cần LLM quyết định
                _upsell_kw = ("béc", "bec", "thân giữ", "than giu", "cách điện",
                              "cach dien", "đi kèm", "di kem", "cần thêm", "can them",
                              "tư vấn", "tu van", "linh kiện", "linh kien", "đồ đi kèm",
                              "vật tư", "vat tu", "tiêu hao", "tieu hao", "sử dụng với",
                              "su dung voi", "dùng với", "dung voi", "đi với", "di voi")
                _needs_upsell = any(kw in query.lower() for kw in _upsell_kw)
                _lookup_ok = any(
                    tr["tool"] == "lookup_part" and
                    (tr.get("result") or {}).get("success", False)
                    for tr in tool_results
                )

                if all_success and _lookup_ok and _needs_upsell and "find_upsell_companions" not in tools_called:
                    # Lấy tokin_part_no từ lookup result
                    _lookup_pno = None
                    for tr in tool_results:
                        if tr["tool"] == "lookup_part":
                            _d = (tr.get("result") or {}).get("data") or {}
                            _lookup_pno = _d.get("tokin_part_no")
                            break
                    if _lookup_pno:
                        log.info(f"[Planner] AUTO-INJECT find_upsell_companions({_lookup_pno})")
                        try:
                            _cat_filter = _detect_category_from_query(query)
                            _upsell_args = {"part_no": _lookup_pno}
                            if _cat_filter:
                                _upsell_args["include_categories"] = _cat_filter
                                log.info(f"[AUTO-INJECT] category_filter={_cat_filter}")
                            _upsell_result = self._dispatch(
                                "find_upsell_companions", _upsell_args
                            )
                        except Exception as _e:
                            _upsell_result = {"success": False, "reason": str(_e)}
                        _upsell_safe = _sanitize(_upsell_result)
                        tool_results.append({
                            "tool": "find_upsell_companions",
                            "args": {"part_no": _lookup_pno},
                            "result": _upsell_safe,
                        })
                        tools_called.append("find_upsell_companions")

                if all_success:
                    log.info(f"[Planner] fast-stop after {tool_call_count} tool(s)")
                    break

            # ── PAGINATION PRE-INJECT (ngoài loop, trước LLM2) ───────────────
            # Khi LLM1 không tự gọi tool nhưng query là "thêm nữa/liệt kê tiếp"
            # → đọc upsell context từ session (lưu cuối turn trước) để page tiếp.
            _pre_args_sdk = OrchestratorV2REST._prep_pre_inject_pagination(
                ctx, query, tools_called)
            if _pre_args_sdk:
                log.info(f"[Planner PRE-INJECT] find_upsell_companions({_pre_args_sdk})")
                try:
                    _pre_result = self._dispatch("find_upsell_companions", _pre_args_sdk)
                except Exception as _pe:
                    _pre_result = {"success": False, "reason": str(_pe)}
                tool_results.append({"tool": "find_upsell_companions",
                                     "args": _pre_args_sdk,
                                     "result": _sanitize(_pre_result)})
                tools_called.append("find_upsell_companions")

            # ── LLM 2: Responder ──────────────────────────────────────────────
            final_text = ""
            if tool_results:
                tool_summary = build_tool_summary(tool_results)
                _context_hint = _build_context_hint(tool_results)
                # Dùng INTENT_MAP giống _extract_session_data để label đúng tool thực chất
                _INTENT_MAP_SDK = {
                    "lookup_part": "LOOKUP", "search_parts": "SEARCH_BY_DESC",
                    "get_consumable_set": "CONSUMABLE_SET", "find_upsell_companions": "UPSELL",
                    "find_replacement": "REPLACEMENT", "check_compatibility": "COMPATIBILITY_CHECK",
                    "compare_parts": "COMPARISON", "get_torches": "AGGREGATE",
                    "get_troubleshoot": "REPAIR", "get_replacement_steps": "INSTALLATION",
                    "get_liner_length": "INSTALLATION",
                }
                _intent_label = next(
                    (_INTENT_MAP_SDK[t] for t in tools_called if t in _INTENT_MAP_SDK),
                    "UNKNOWN"
                )
                responder_prompt = (
                    f"[INTENT: {_intent_label}]\n"
                    f"Câu hỏi của khách: {query}\n\n"
                    f"{_context_hint}"
                    f"Kết quả từ tools:\n{tool_summary}"
                    f"{_SYNTHESIS_RULES}"
                )
                resp_msgs = [_to_content(m) for m in base_history]
                resp_msgs.append(gt.Content(role="user",
                    parts=[gt.Part.from_text(text=responder_prompt)]))

                log.info(f"[Responder] synthesizing {len(tool_results)} results")
                resp2 = client.models.generate_content(
                    model   = self.model,
                    contents= resp_msgs,
                    config  = gt.GenerateContentConfig(
                        system_instruction = _RESPONDER_SYSTEM,
                        temperature        = RESPONDER_TEMP,
                        max_output_tokens  = 2500,
                        thinking_config    = gt.ThinkingConfig(thinking_budget=0),
                    ),
                )
                if resp2.candidates and resp2.candidates[0].content:
                    final_text = "\n".join(
                        p.text for p in (resp2.candidates[0].content.parts or [])
                        if hasattr(p,"text") and p.text
                    ).strip()
            else:
                last_model = next(
                    (m for m in reversed(current)
                     if hasattr(m,"role") and m.role=="model"), None,
                )
                if last_model and last_model.parts:
                    final_text = "\n".join(
                        p.text for p in last_model.parts
                        if hasattr(p,"text") and p.text
                    ).strip()

            if not final_text:
                final_text = "Dạ em xin lỗi, có lỗi xảy ra. Anh/chị vui lòng thử lại ạ."

        except Exception as e:
            return _error_response(exc=e, tools_called=tools_called,
                tool_results=tool_results, t0=t0, model=self.model,
                prefix="OrchestratorV2")

        intent, entities, returned = _extract_session_data(tools_called, tool_results, query)
        safe_ent = _sanitize(entities)
        if ctx:
            self._ss.update(ctx, intent, safe_ent, returned,
                            query=query, response_text=final_text[:200])
            # Lưu upsell context để PRE-INJECT dùng ở turn tiếp theo
            for _tr in tool_results:
                if _tr.get("tool") == "find_upsell_companions":
                    _a = _tr.get("args", {})
                    if _a.get("part_no"):
                        # FIX (restructure): field chính thức trên SessionContext
                        # (hack __dict__ cũ bị mất khi serialize Redis)
                        ctx.last_upsell_pno  = _a["part_no"]
                        ctx.last_upsell_page = _a.get("page", 1)
                        ctx.last_upsell_cats = _a.get("include_categories", [])
                    break

        # ── ORDER FLOW ────────────────────────────────────────────────────────
        try:
            from core.order_manager import (
                get_or_create_order, detect_order_trigger,
                parse_order_from_query, process_slot_answer, finalize_order,
                SLOT_QUESTIONS,
            )
            _order_text = None
            if ctx:
                _os = get_or_create_order(ctx)
                # Đang trong slot-filling flow
                if _os.current_slot and not _os.confirmed:
                    _next_q = process_slot_answer(_os, query)
                    if _next_q is None and _os.next_empty_slot is None:
                        # Xong hết slots → finalize
                        _order_text = finalize_order(_os, ctx)
                    elif _next_q:
                        _order_text = _next_q
                # Trigger chốt đơn mới — chỉ khi đã có tool_results (đang tư vấn part cụ thể)
                elif detect_order_trigger(query) and not _os.confirmed and tool_results:
                    _upsell_ctx = {
                        "part_no":    getattr(ctx, "last_upsell_pno", ""),
                        "name":       "",
                        "unit_price": 0,
                    }
                    # Lấy price từ tool_results nếu có
                    for _tr in tool_results:
                        _rd = (_tr.get("result") or {})
                        for _comp in (_rd.get("companions") or []):
                            if isinstance(_comp, dict) and _comp.get("tokin_part_no") == _upsell_ctx["part_no"]:
                                _upsell_ctx["unit_price"] = _comp.get("price_vnd", 0)
                                _upsell_ctx["name"] = _comp.get("display_name_vi", "")
                                break
                    _items = parse_order_from_query(query, _upsell_ctx)
                    if _items:
                        _os.items = _items
                        _os.current_slot = "ho_ten"
                        # Tóm tắt đơn + hỏi slot đầu
                        _order_text = _os.format_items() + "\n\n" + SLOT_QUESTIONS["ho_ten"]
            if _order_text:
                final_text = _order_text
        except Exception as _oe:
            log.warning(f"[OrderFlow] error: {_oe}")

        latency_ms = int((time.time()-t0)*1000)
        log.info(f"[OrchestratorV2] done {latency_ms}ms tools={tools_called} intent={intent}")
        return OrchestratorResponse(
            text=final_text, tools_called=tools_called, tool_results=tool_results,
            intent=intent, entities=safe_ent, success=True,
            latency_ms=latency_ms, model=self.model,
        )


# ══════════════════════════════════════════════════════════════════════════════
# OrchestratorV2REST — urllib fallback
# ══════════════════════════════════════════════════════════════════════════════

class OrchestratorV2REST:
    URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "{model}:generateContent?key={api_key}")

    def __init__(self, api_key: str = GEMINI_API_KEY, model: str = GEMINI_MODEL):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY","")
        self.model   = model
        from core.system_prompts import ASSISTANT_PROMPT, TOOL_SCHEMA
        self._planner_system = ASSISTANT_PROMPT
        self._tool_schema    = TOOL_SCHEMA
        from core.session_store import get_session_store
        self._ss = get_session_store()
        from core.tool_wrappers import dispatch as _d
        self._dispatch = _d
        log.info(f"[OrchestratorV2REST] init model={self.model}")

    def _post(self, payload: dict) -> dict:
        # FIX (restructure):
        #   1. Bỏ log API key (security leak — key từng bị in 20 ký tự đầu mỗi request)
        #   2. Wrap retry 429/5xx/timeout qua gemini_resilience.retry_http
        import urllib.request
        from core.gemini_resilience import retry_http
        url  = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = json.dumps(payload).encode("utf-8")

        def _do():
            req = urllib.request.Request(url, data=body,
                  headers={"Content-Type":"application/json","x-goog-api-key":self.api_key}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                log.error(f"[REST._post] HTTP {e.code}: {err_body[:500]}")
                raise

        return retry_http(_do, label="orch_v2_rest")

    def _post_stream(self, payload: dict):
        """
        Gọi streamGenerateContent → yield từng chunk text.
        Dùng cho Responder streaming (LLM 2 không có function calls).
        """
        import urllib.request, urllib.error
        url  = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:streamGenerateContent?alt=sse"
        body = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(url, data=body,
               headers={"Content-Type":"application/json","x-goog-api-key":self.api_key}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                buf = ""
                while True:
                    line = r.readline()
                    if not line:
                        break
                    line = line.decode("utf-8").rstrip("\n\r")
                    if line.startswith("data: "):
                        raw = line[6:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(raw)
                            parts = (chunk.get("candidates", [{}])[0]
                                     .get("content", {}).get("parts", []))
                            for p in parts:
                                txt = p.get("text", "")
                                if txt:
                                    yield txt
                        except json.JSONDecodeError:
                            continue
        except urllib.error.HTTPError as e:
            body_err = e.read().decode("utf-8")
            log.error(f"[REST._post_stream] HTTP {e.code}: {body_err[:300]}")
            raise

    def stream_response(self, query: str, session_id=None, history=None):
        """
        Generator: chạy Planner (blocking) → stream Responder từng chunk.

        Yield các dict:
          {"type": "tool_start", "tool": "search_parts"}
          {"type": "tool_done",  "tool": "search_parts", "ms": 120}
          {"type": "text",       "chunk": "Dạ "}
          {"type": "text",       "chunk": "em tìm thấy..."}
          {"type": "done",       "intent": "SEARCH_BY_DESC", "latency_ms": 3200}
          {"type": "error",      "message": "..."}
        """
        import base64
        t0 = time.time()

        # OOS fast-path
        oos = _detect_oos(query)
        if oos:
            ctx = self._ss.get_or_create(session_id)
            if ctx:
                self._ss.update(ctx, "OUT_OF_SCOPE", {}, [], query=query, response_text=oos)
            # Stream OOS từng từ để có hiệu ứng
            for word in oos.split(" "):
                yield {"type": "text", "chunk": word + " "}
            yield {"type": "done", "intent": "OUT_OF_SCOPE",
                   "latency_ms": int((time.time()-t0)*1000)}
            return

        ctx      = self._ss.get_or_create(session_id)
        contents = _build_history(ctx, history)
        contents.append({"role": "user", "parts": [{"text": query}]})

        tools_called: List[str]  = []
        tool_results: List[dict] = []
        tool_call_count = 0

        planner_payload = {
            "systemInstruction": {"parts": [{"text": self._planner_system}]},
            "tools":             self._tools(),
            "tool_config": {
                "function_calling_config": {"mode": "ANY"}
            },
            "generationConfig":  {
                "temperature":    PLANNER_TEMP,
                "maxOutputTokens": MAX_OUTPUT_TOKENS,
                "thinkingConfig": {"thinkingBudget": 0},
            },
            "contents": contents,
        }

        try:
            # ── LLM 1: Planner (blocking — cần function calls) ────────────────
            current = list(contents)
            while tool_call_count <= MAX_TOOL_CALLS:
                # FIX (restructure): deadline tổng — không để 1 request kéo dài
                # quá REQUEST_BUDGET_S (planner loop + retry có thể cộng dồn)
                if time.time() - t0 > REQUEST_BUDGET_S:
                    log.warning(f"[run] request budget {REQUEST_BUDGET_S}s exceeded "
                                f"after {tool_call_count} tool rounds — synthesize now")
                    break
                planner_payload["contents"] = current
                data  = self._post(planner_payload)
                parts = (data.get("candidates", [{}])[0]
                         .get("content", {}).get("parts", []))
                fc_parts = [p for p in parts if "functionCall" in p]

                if not fc_parts:
                    current.append({"role": "model", "parts": parts})
                    break
                if tool_call_count >= MAX_TOOL_CALLS:
                    current.append({"role": "model", "parts": parts})
                    break

                current.append({"role": "model", "parts": parts})

                # ── Parallel tool execution ───────────────────────────────────
                # Yield tool_start cho tất cả trước khi chạy
                for fc in fc_parts:
                    yield {"type": "tool_start", "tool": fc["functionCall"]["name"]}

                fn_resps = []
                parallel_results = self._run_tools_parallel(fc_parts)
                for fn_name, fn_args, safe, tool_ms in parallel_results:
                    tools_called.append(fn_name)
                    tool_results.append({"tool": fn_name, "args": fn_args, "result": safe})
                    fn_resps.append({"functionResponse": {"name": fn_name, "response": safe}})
                    yield {"type": "tool_done", "tool": fn_name, "ms": tool_ms}

                current.append({"role": "user", "parts": fn_resps})
                tool_call_count += 1

                all_success = all(
                    (tr.get("result") or {}).get("success", False)
                    for tr in tool_results
                )

                if all_success:
                    # Pagination AUTO-INJECT: tìm part_no + page từ history
                    _pag_args = self._prep_pagination_from_history(
                        query, contents, tools_called)
                    if _pag_args:
                        log.info(f"[REST] PAGINATION-INJECT find_upsell_companions({_pag_args})")
                        self._exec_inject("find_upsell_companions", _pag_args,
                                          tools_called, tool_results)
                    # AUTO-INJECT: lookup_part OK + query upsell
                    _ups_args = self._prep_auto_upsell(query, tools_called, tool_results)
                    if _ups_args:
                        log.info(f"[REST] AUTO-INJECT find_upsell_companions({_ups_args})")
                        self._exec_inject("find_upsell_companions", _ups_args,
                                          tools_called, tool_results)
                    break

            # ── PAGINATION PRE-INJECT (ngoài loop, trước LLM2) ────────────────
            # Chạy khi LLM1 không gọi tool nào nhưng query là "thêm nữa/liệt kê tiếp"
            _pre_args = self._prep_pre_inject_pagination(ctx, query, tools_called)
            if _pre_args:
                log.info(f"[PRE-INJECT PAGINATION] find_upsell_companions({_pre_args})")
                yield {"type": "tool_start", "tool": "find_upsell_companions"}
                self._exec_inject("find_upsell_companions", _pre_args,
                                  tools_called, tool_results)
                yield {"type": "tool_done", "tool": "find_upsell_companions", "ms": 0}

            # ── LLM 2: Responder (streaming) ──────────────────────────────────
            full_text = ""
            if tool_results:
                tool_summary = build_tool_summary(tool_results)
                _context_hint = _build_context_hint(tool_results)
                responder_prompt = (
                    f"Câu hỏi của khách: {query}\n\n"
                    f"{_context_hint}"
                    f"Kết quả từ tools:\n{tool_summary}"
                    f"{_SYNTHESIS_RULES}"
                )
                resp_payload = {
                    "systemInstruction": {"parts": [{"text": _RESPONDER_SYSTEM}]},
                    "generationConfig":  {
                        "temperature":    RESPONDER_TEMP,
                        "maxOutputTokens": 2500,
                        "thinkingConfig": {"thinkingBudget": 0},
                    },
                    "contents": [
                        *[m for m in contents],
                        {"role": "user", "parts": [{"text": responder_prompt}]},
                    ],
                }
                for chunk in self._post_stream(resp_payload):
                    full_text += chunk
                    yield {"type": "text", "chunk": chunk}
            else:
                # Planner trả lời trực tiếp — không có tool → stream từng từ
                last = next((m for m in reversed(current) if m.get("role") == "model"), None)
                if last:
                    text = "\n".join(
                        p.get("text", "") for p in last.get("parts", []) if "text" in p
                    ).strip()
                    full_text = text
                    # Stream từng chunk ~20 chars để có hiệu ứng
                    chunk_size = 20
                    for i in range(0, len(text), chunk_size):
                        yield {"type": "text", "chunk": text[i:i+chunk_size]}

            if not full_text:
                full_text = "Dạ em xin lỗi, có lỗi xảy ra. Anh/chị vui lòng thử lại ạ."
                yield {"type": "text", "chunk": full_text}

        except Exception as e:
            err_type, vi_msg = _classify_error(e)
            log.error(f"[OrchestratorV2REST.stream] {err_type}: {e}")
            yield {"type": "error", "message": vi_msg}
            full_text = vi_msg
            intent, entities, returned = "error", {}, []
        else:
            intent, entities, returned = _extract_session_data(tools_called, tool_results, query)

        safe_ent = _sanitize(entities)
        if ctx:
            self._ss.update(ctx, intent, safe_ent, returned,
                            query=query, response_text=full_text[:200])
            self._save_upsell_ctx(ctx, tool_results)
        yield {"type": "done", "intent": intent,
               "latency_ms": int((time.time()-t0)*1000),
               "tools_called": tools_called}

    # ══════════════════════════════════════════════════════════════════════
    # Inject helpers — dùng chung cho run() và stream_response()
    # FIX (restructure 2026-06): trước đây logic này bị copy 2-3 bản và chỉ
    # tồn tại trong stream_response() — run() (pipeline /api/v2/query) thiếu
    # hẳn pagination/upsell inject. Gom về 1 chỗ, 2 path gọi chung.
    # ══════════════════════════════════════════════════════════════════════

    def _exec_inject(self, tool_name: str, args: dict,
                     tools_called: list, tool_results: list) -> None:
        """Dispatch 1 tool inject + append kết quả vào tools_called/tool_results."""
        try:
            result = self._dispatch(tool_name, args)
        except Exception as e:
            result = {"success": False, "reason": str(e)}
        tool_results.append({"tool": tool_name, "args": args,
                             "result": _sanitize(result)})
        tools_called.append(tool_name)

    @staticmethod
    def _prep_pagination_from_history(query: str, contents: list,
                                      tools_called: list) -> Optional[dict]:
        """
        In-loop PAGINATION: query là 'liệt kê tiếp/xem thêm...' → tìm part_no,
        page, include_categories từ history. Trả về args cho
        find_upsell_companions, hoặc None nếu không áp dụng.
        """
        if not _is_pagination_query(query):
            return None
        if "find_upsell_companions" in tools_called:
            return None
        import re as _re
        _prev_pno  = None
        _prev_page = 1
        _prev_cat: list = []
        _last_assistant_text = ""
        for _msg in reversed(contents[:-1]):
            _msg_text = str(_msg)
            # Tìm part_no từ tool result trong history
            _pno_match = _re.search(r'tokin_part_no["\s:]+([0-9A-Z]{6,})', _msg_text)
            if _pno_match:
                _prev_pno = _pno_match.group(1)
            _page_match = _re.search(r'"page":\s*(\d+)', _msg_text)
            if _page_match:
                _prev_page = int(_page_match.group(1))
            # Tìm include_categories từ history (nếu đã được set trước đó)
            _cat_match = _re.search(r'include_categories.*?\[([^\]]+)\]', _msg_text)
            if _cat_match:
                _prev_cat = [c.strip().strip('"\'') for c in _cat_match.group(1).split(',')]
            # Lưu assistant message gần nhất để detect category đã trả
            if not _last_assistant_text and "role='model'" in _msg_text:
                _last_assistant_text = _msg_text.lower()
            if _prev_pno:
                break
        if not _prev_pno:
            return None
        # Nếu chưa có category → detect từ nội dung assistant đã trả
        if not _prev_cat and _last_assistant_text:
            _detected_cats: list = []
            for _kw, _cat in _CAT_KEYWORD_MAP.items():
                if _kw in _last_assistant_text and _cat not in _detected_cats:
                    _detected_cats.append(_cat)
            # Chỉ 1 category được trả ở turn trước → page tiếp category đó
            if len(_detected_cats) == 1:
                _prev_cat = _detected_cats
                log.info(f"[PAGINATION] Category lock from prev assistant: {_prev_cat}")
        args = {"part_no": _prev_pno, "page": _prev_page + 1}
        if _prev_cat:
            args["include_categories"] = _prev_cat
        return args

    @staticmethod
    def _prep_auto_upsell(query: str, tools_called: list,
                          tool_results: list) -> Optional[dict]:
        """
        AUTO-INJECT: lookup_part thành công + query có ý upsell →
        args cho find_upsell_companions, hoặc None nếu không áp dụng.
        """
        if not _needs_upsell_query(query):
            return None
        if "find_upsell_companions" in tools_called:
            return None
        _lookup_ok = any(
            tr["tool"] == "lookup_part" and
            (tr.get("result") or {}).get("success", False)
            for tr in tool_results
        )
        if not _lookup_ok:
            return None
        _lookup_pno = None
        for tr in tool_results:
            if tr["tool"] == "lookup_part":
                _d = (tr.get("result") or {}).get("data") or {}
                _lookup_pno = _d.get("tokin_part_no")
                break
        if not _lookup_pno:
            return None
        args = {"part_no": _lookup_pno}
        _cat_filter = _detect_category_from_query(query)
        if _cat_filter:
            args["include_categories"] = _cat_filter
            log.info(f"[AUTO-INJECT] category_filter={_cat_filter}")
        return args

    @staticmethod
    def _prep_pre_inject_pagination(ctx, query: str,
                                    tools_called: list) -> Optional[dict]:
        """
        PRE-INJECT (ngoài loop, trước LLM2): LLM1 không tự gọi tool nhưng
        query là 'thêm nữa/liệt kê tiếp' → đọc upsell context từ session
        (lưu cuối turn trước) để page tiếp.
        """
        if not _is_pagination_query(query):
            return None
        if "find_upsell_companions" in tools_called:
            return None
        _prev_pno  = getattr(ctx, "last_upsell_pno",  None) if ctx else None
        _prev_page = getattr(ctx, "last_upsell_page", 1)    if ctx else 1
        _prev_cat  = getattr(ctx, "last_upsell_cats", [])   if ctx else []
        log.info(f"[PRE-INJECT PAGINATION] ctx read: pno={_prev_pno} "
                 f"page={_prev_page} cats={_prev_cat}")
        if not _prev_pno:
            return None
        args = {"part_no": _prev_pno, "page": _prev_page + 1}
        if _prev_cat:
            args["include_categories"] = _prev_cat
        return args

    @staticmethod
    def _save_upsell_ctx(ctx, tool_results: list) -> None:
        """Lưu upsell context vào session để PRE-INJECT dùng ở turn tiếp theo."""
        if ctx is None:
            return
        for _tr in tool_results:
            if _tr.get("tool") == "find_upsell_companions":
                _a = _tr.get("args", {})
                if _a.get("part_no"):
                    ctx.last_upsell_pno  = _a["part_no"]
                    ctx.last_upsell_page = _a.get("page", 1)
                    ctx.last_upsell_cats = _a.get("include_categories", [])
                break

    def _run_tools_parallel(self, fc_parts: list) -> list:
        """
        Chạy nhiều function calls song song bằng ThreadPoolExecutor.
        Trả về list (fn_name, fn_args, safe_result, latency_ms) theo thứ tự fc_parts.

        Parallel khi ≥2 tools — fallback tuần tự nếu lỗi.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _call_one(fc):
            fn      = fc["functionCall"]
            fn_name = fn["name"]
            fn_args = _to_python(fn.get("args", {}))
            t_tool  = time.time()
            try:
                result = self._dispatch(fn_name, fn_args)
            except Exception as e:
                log.error(f"[Parallel] {fn_name} error: {e}")
                result = {"success": False, "reason": str(e)}
            safe = _sanitize(result)
            ms   = int((time.time() - t_tool) * 1000)
            log.info(f"[Parallel] {fn_name} done {ms}ms")
            return fn_name, fn_args, safe, ms

        if len(fc_parts) == 1:
            # Single tool — không cần thread overhead
            return [_call_one(fc_parts[0])]

        results_map: dict = {}
        try:
            with ThreadPoolExecutor(max_workers=min(len(fc_parts), 4)) as ex:
                futures = {ex.submit(_call_one, fc): i for i, fc in enumerate(fc_parts)}
                for fut in as_completed(futures):
                    idx = futures[fut]
                    results_map[idx] = fut.result()
        except Exception as e:
            log.warning(f"[Parallel] ThreadPool error → fallback sequential: {e}")
            return [_call_one(fc) for fc in fc_parts]

        # Giữ thứ tự theo fc_parts
        return [results_map[i] for i in range(len(fc_parts))]

    def _tools(self) -> list:
        return [{"functionDeclarations": [
            {"name":t["name"],"description":t["description"],
             "parameters":t.get("parameters",{})}
            for t in self._tool_schema
        ]}]

    def run(self, query: str, session_id=None, history=None,
            image_data=None, image_mime="image/jpeg") -> OrchestratorResponse:
        import base64
        t0 = time.time()

        if not image_data:
            oos = _detect_oos(query)
            if oos:
                ctx = self._ss.get_or_create(session_id)
                if ctx:
                    self._ss.update(ctx,"OUT_OF_SCOPE",{},[],query=query,response_text=oos)
                return OrchestratorResponse(text=oos, intent="OUT_OF_SCOPE",
                    success=True, latency_ms=int((time.time()-t0)*1000), model="oos_fast_path")

        ctx      = self._ss.get_or_create(session_id)
        contents = _build_history(ctx, history)

        user_parts: list = []
        if image_data:
            user_parts.append({"inlineData":{"mimeType":image_mime,
                "data":base64.b64encode(image_data).decode()}})
        user_parts.append({"text": query})
        contents.append({"role":"user","parts":user_parts})

        tools_called: List[str]  = []
        tool_results: List[dict] = []
        tool_call_count = 0

        planner_payload = {
            "systemInstruction": {"parts":[{"text":self._planner_system}]},
            "tools":             self._tools(),
            # FIX (eval 2026-06): ép Planner gọi tool (mode ANY) — đồng bộ với
            # stream_response(). Trước đây run() thiếu config này → 129/239
            # case fail vì "no_tool_called". OOS đã được chặn trước bằng
            # _detect_oos nên không sợ ép tool với câu chit-chat.
            "tool_config": {
                "function_calling_config": {"mode": "ANY"}
            },
            "generationConfig":  {"temperature":PLANNER_TEMP,"maxOutputTokens":MAX_OUTPUT_TOKENS,"thinkingConfig":{"thinkingBudget":0}},
            "contents":          contents,
        }

        try:
            current = list(contents)
            while tool_call_count <= MAX_TOOL_CALLS:
                # FIX (restructure): deadline tổng — không để 1 request kéo dài
                # quá REQUEST_BUDGET_S (planner loop + retry có thể cộng dồn)
                if time.time() - t0 > REQUEST_BUDGET_S:
                    log.warning(f"[run] request budget {REQUEST_BUDGET_S}s exceeded "
                                f"after {tool_call_count} tool rounds — synthesize now")
                    break
                planner_payload["contents"] = current
                data  = self._post(planner_payload)
                parts = (data.get("candidates",[{}])[0]
                         .get("content",{}).get("parts",[]))
                fc_parts = [p for p in parts if "functionCall" in p]

                if not fc_parts:
                    current.append({"role":"model","parts":parts})
                    break
                if tool_call_count >= MAX_TOOL_CALLS:
                    current.append({"role":"model","parts":parts})
                    break

                current.append({"role":"model","parts":parts})

                # ── Parallel tool execution ───────────────────────────────────
                fn_resps = []
                parallel_results = self._run_tools_parallel(fc_parts)
                for fn_name, fn_args, safe, tool_ms in parallel_results:
                    tools_called.append(fn_name)
                    tool_results.append({"tool":fn_name,"args":fn_args,"result":safe})
                    fn_resps.append({"functionResponse":{"name":fn_name,"response":safe}})
                    log.info(f"[run] tool {fn_name} {tool_ms}ms success={safe.get('success')}")

                current.append({"role":"user","parts":fn_resps})
                tool_call_count += 1

                # FIX (eval 2026-06): đồng bộ với stream_response() — với mode
                # ANY, Planner luôn bị ép gọi tool nên PHẢI break khi tất cả
                # tool đã thành công, nếu không loop sẽ chạy đủ MAX_TOOL_CALLS.
                all_success = all(
                    (tr.get("result") or {}).get("success", False)
                    for tr in tool_results
                )
                if all_success:
                    # Pagination AUTO-INJECT: tìm part_no + page từ history
                    _pag_args = self._prep_pagination_from_history(
                        query, contents, tools_called)
                    if _pag_args:
                        log.info(f"[run] PAGINATION-INJECT find_upsell_companions({_pag_args})")
                        self._exec_inject("find_upsell_companions", _pag_args,
                                          tools_called, tool_results)
                    # AUTO-INJECT: lookup_part OK + query upsell
                    _ups_args = self._prep_auto_upsell(query, tools_called, tool_results)
                    if _ups_args:
                        log.info(f"[run] AUTO-INJECT find_upsell_companions({_ups_args})")
                        self._exec_inject("find_upsell_companions", _ups_args,
                                          tools_called, tool_results)
                    break

            # PAGINATION PRE-INJECT (ngoài loop) — LLM1 không gọi tool nhưng
            # query là "thêm nữa/liệt kê tiếp" → đọc upsell context từ session
            _pre_args = self._prep_pre_inject_pagination(ctx, query, tools_called)
            if _pre_args:
                log.info(f"[run] PRE-INJECT find_upsell_companions({_pre_args})")
                self._exec_inject("find_upsell_companions", _pre_args,
                                  tools_called, tool_results)

            final_text = ""
            if tool_results:
                # Smart truncate: UPSELL/CONSUMABLE có nhiều parts → giới hạn chặt hơn
                tool_summary = build_tool_summary(tool_results)
                _context_hint = _build_context_hint(tool_results)
                # Dùng INTENT_MAP giống _extract_session_data để label đúng tool thực chất
                _INTENT_MAP_REST = {
                    "lookup_part": "LOOKUP", "search_parts": "SEARCH_BY_DESC",
                    "get_consumable_set": "CONSUMABLE_SET", "find_upsell_companions": "UPSELL",
                    "find_replacement": "REPLACEMENT", "check_compatibility": "COMPATIBILITY_CHECK",
                    "compare_parts": "COMPARISON", "get_torches": "AGGREGATE",
                    "get_troubleshoot": "REPAIR", "get_replacement_steps": "INSTALLATION",
                    "get_liner_length": "INSTALLATION",
                }
                _intent_label_r = next(
                    (_INTENT_MAP_REST[t] for t in tools_called if t in _INTENT_MAP_REST),
                    "UNKNOWN"
                )
                resp2 = self._post({
                    "systemInstruction":{"parts":[{"text":_RESPONDER_SYSTEM}]},
                    "generationConfig": {"temperature":RESPONDER_TEMP,"maxOutputTokens":2500,"thinkingConfig":{"thinkingBudget":0}},
                    "contents": [
                        *[m for m in contents],
                        {"role":"user","parts":[{"text":
                            f"[INTENT: {_intent_label_r}]\n"
                            f"Câu hỏi của khách: {query}\n\n"
                            f"{_context_hint}"
                            f"Kết quả từ tools:\n{tool_summary}"
                            f"{_SYNTHESIS_RULES}"
                        }]},
                    ],
                })
                final_text = "\n".join(
                    p.get("text","") for p in
                    resp2.get("candidates",[{}])[0].get("content",{}).get("parts",[])
                    if "text" in p
                ).strip()
            else:
                last = next((m for m in reversed(current) if m.get("role")=="model"), None)
                if last:
                    final_text = "\n".join(
                        p.get("text","") for p in last.get("parts",[]) if "text" in p
                    ).strip()

            if not final_text:
                final_text = "Dạ em xin lỗi, có lỗi xảy ra. Anh/chị vui lòng thử lại ạ."

        except Exception as e:
            return _error_response(exc=e, tools_called=tools_called,
                tool_results=tool_results, t0=t0, model=self.model,
                prefix="OrchestratorV2REST")

        intent, entities, returned = _extract_session_data(tools_called, tool_results, query)
        safe_ent = _sanitize(entities)
        if ctx:
            self._ss.update(ctx, intent, safe_ent, returned,
                            query=query, response_text=final_text[:200])
            self._save_upsell_ctx(ctx, tool_results)
        latency_ms = int((time.time()-t0)*1000)
        return OrchestratorResponse(
            text=final_text, tools_called=tools_called, tool_results=tool_results,
            intent=intent, entities=safe_ent, success=True,
            latency_ms=latency_ms, model=self.model,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Factory + Singleton
# ══════════════════════════════════════════════════════════════════════════════

def get_orchestrator(api_key: str = GEMINI_API_KEY, model: str = GEMINI_MODEL,
                     force_rest: bool = False):
    if not force_rest:
        try:
            import google.genai  # noqa
            return OrchestratorV2(api_key=api_key, model=model)
        except ImportError:
            log.info("[get_orchestrator] google.genai not found → REST fallback")
    return OrchestratorV2REST(api_key=api_key, model=model)


_orch_instance = None

def get_orchestrator_singleton(api_key: str = GEMINI_API_KEY, model: str = GEMINI_MODEL):
    global _orch_instance
    if _orch_instance is None:
        _orch_instance = get_orchestrator(api_key=api_key, model=model, force_rest=True)
    return _orch_instance





