# DOC STATUS — Trạng thái tài liệu

> **Bản này: ĐÃ SẴN SÀNG CODE.** (cập nhật sau khi gộp chatbot thật + fix tài liệu)

Dùng file này để nhận diện đúng bản zip mới nhất. Nếu file này tồn tại và ghi
"ĐÃ SẴN SÀNG CODE" → đây là bản đã fix đầy đủ.

---

## Tài liệu — trạng thái

| Phần | Trạng thái |
|---|---|
| Backend (CRM/WMS/Sales/Analytics/Catalog) | ✅ Tài liệu khớp code thật |
| ERD / LLD / B2 Database / B3 API | ✅ Đúng (phần backend) |
| LLD §7 bảng hiện trạng | ✅ Cập nhật đúng trạng thái sau merge (chatbot thật + handlers + FE slice 1) |
| Event bus + handlers | ✅ Đúng |
| Frontend (DEV_SETUP, FRONTEND_GUIDE, B4) | ✅ Đúng — lưu ý FE mới code Slice 1 |
| Chatbot — `chatbot/README.md` | ✅ MỚI, khớp chatbot thật v8.0 |
| CI (`.github/workflows/ci.yml`) | ✅ Đã gỡ bước role-sync gây đỏ |
| DEV_SETUP §3 chatbot | ✅ Viết lại đúng X-API-Key |
| TROUBLESHOOTING §3-6 | ✅ Viết lại cho chatbot thật |
| Doc chatbot CŨ (B1/B5/LLD/CHATBOT_TOOL_GUIDE/B0) | ⚠️ Có BANNER "lỗi thời" — giữ tham khảo lịch sử |
| Changelog `docs/implementation/*` | Giữ nguyên (bản ghi lịch sử) |

## Phân quyền

| Tầng | Trạng thái |
|---|---|
| Thiết kế (B2/B3/B5) | ✅ Đặc tả đầy đủ |
| Backend permission + test | ✅ Xong (cho app đã code) |
| Frontend RequireRole | 🟡 Đã thiết kế (B4), CHƯA code (FE mới Slice 1) |

## Việc runtime cần chú ý (không phải lỗi tài liệu)

1. nginx forward `Authorization` nhưng chatbot cần `X-API-Key` — xem
   `docs/implementation/V6_MERGE_chatbot_real.md` §3.2.
2. Model bge-m3 (~2GB) tải runtime lần đầu — cache qua volume `hf_cache`.
3. `chatbot/.env` chứa key thật — đừng push lên git public.

## Bắt đầu code từ đâu

→ `docs/dev/DEV_SETUP.md` (onboarding) → `chatbot/README.md` (chatbot) →
`docs/dev/API_REFERENCE.md` (backend) → `docs/dev/FRONTEND_GUIDE.md` (FE) →
`EXTENDING.md` (quy ước + checklist PR).
