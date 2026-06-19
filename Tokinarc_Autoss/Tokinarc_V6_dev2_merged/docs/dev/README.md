# Tokinarc V6 — Dev Documentation Index

> Tài liệu cho dev hàng ngày. Đọc theo thứ tự tùy mục đích.

---

## Bắt đầu

| File | Khi nào đọc |
|---|---|
| [`DEV_SETUP.md`](DEV_SETUP.md) | **Lần đầu** clone repo. 30 phút từ git clone → full stack chạy. |
| [`../../EXTENDING.md`](../../EXTENDING.md) | **Trước khi mở PR đầu tiên**. 5 nguyên tắc + checklist 8 bước. |

## Tham khảo hàng ngày

| File | Khi nào dùng |
|---|---|
| [`API_REFERENCE.md`](API_REFERENCE.md) | Cần endpoint backend cụ thể, request/response shape, curl example. |
| [`../../chatbot/README.md`](../../chatbot/README.md) | **Chatbot THẬT v8.0** — setup, endpoint, env, thêm tool, rebuild index, eval. |
| [`CHATBOT_TOOL_GUIDE.md`](CHATBOT_TOOL_GUIDE.md) | ⚠️ LỖI THỜI (chatbot sidecar cũ). Dùng `chatbot/README.md` thay thế. |
| [`FRONTEND_GUIDE.md`](FRONTEND_GUIDE.md) | Thêm page mới FE. Theme tokens, pattern form, React Query. |
| [`EVENTS_HANDLERS.md`](EVENTS_HANDLERS.md) | Thêm event async / handler. Idempotency + bẫy circular import. |
| [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | Khi gặp lỗi. 20 lỗi thường gặp + fix. |

## Tài liệu thiết kế (deep dive)

| File | Khi nào đọc |
|---|---|
| [`../architecture/Tokinarc_V6_LLD_DataFlow.md`](../architecture/Tokinarc_V6_LLD_DataFlow.md) | Hiểu data flow toàn hệ thống. Có 8 sequence diagram. |
| [`../architecture/Tokinarc_V6_ERD.md`](../architecture/Tokinarc_V6_ERD.md) | Quan hệ giữa 43 model (ERD mermaid theo domain CRM/Sales/WMS). Đọc trước khi đụng schema/FK. |
| [`../architecture/Tokinarc_V6_B0_Index.md`](../architecture/Tokinarc_V6_B0_Index.md) | Thiết kế gốc B0-B6 (lưu ý: có chỗ đã lỗi thời, LLD mới hơn). |
| [`../implementation/V6_C_fix3_CRM_Changelog.md`](../implementation/V6_C_fix3_CRM_Changelog.md) | Lịch sử thay đổi cụ thể từng đợt fix. |

---

## Cheat sheet câu hỏi thường gặp

### "Tôi muốn thêm field mới cho Customer"

→ [`../../EXTENDING.md`](../../EXTENDING.md) §2 (quy ước model + index)
→ Sửa `apps/crm/models.py`, `serializers.py`, `views.py` nếu cần expose
→ Chạy `makemigrations crm` + thêm test
→ Update FE type `types.ts` (nếu user thấy field này)

### "Tôi muốn bot trả lời 1 câu hỏi mới / thêm tool tra cứu"

→ [`../../chatbot/README.md`](../../chatbot/README.md) §7 — thêm function vào `core/tool_wrappers.py` + schema vào `core/system_prompts.py`

### "Tôi muốn thêm trang Quotes"

→ [`FRONTEND_GUIDE.md`](FRONTEND_GUIDE.md) §2 "Thêm 1 page mới" — Worked example

### "Tôi muốn gửi email khi quote approved"

→ [`EVENTS_HANDLERS.md`](EVENTS_HANDLERS.md) — pattern subscribe + idempotency

### "Bot không nhận quyền của user"

→ [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) §4 + [`CHATBOT_TOOL_GUIDE.md`](CHATBOT_TOOL_GUIDE.md) §"3 lớp phân quyền"

### "Migration drift sau khi pull"

→ [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) §2

### "CI báo role tables sync fail"

→ [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) §3 (1 lệnh fix)

---

## Quy ước chung

### Code style

- **Python**: Ruff (cài `ruff==0.4.7`). Format `black` compatible.
- **TypeScript**: Prettier + ESLint strict.
- **Commit**: tiếng Việt OK. Prefix `[backend]` / `[chatbot]` / `[fe]` / `[infra]`.

### Branch

- `main` — production-ready
- `develop` — staging
- Feature branch: `feature/<short-name>`, vd `feature/crm-quote-cancel`
- Bug fix: `fix/<short-name>`

### PR

Trước khi merge, đảm bảo:

- [ ] `pytest apps/ -q` xanh ở local
- [ ] `python manage.py makemigrations --check --dry-run` xanh
- [ ] `python manage.py dump_roles --format=py --out ../chatbot/roles_generated.py --check` xanh (nếu sửa roles.py)
- [ ] `ruff check backend/` xanh
- [ ] FE: `npm run build` xanh (nếu sửa FE)
- [ ] Update `CHANGELOG.md` hoặc `docs/implementation/V6_C_X_Changelog.md`

### Yêu cầu cho ticket / PR description

Template tối thiểu:

```markdown
## Mục tiêu
Mô tả tính năng 1-2 câu.

## Thay đổi
- [ ] File 1: ...
- [ ] File 2: ...

## Test
- [ ] Unit: `pytest apps/<app>/tests/test_<file>.py`
- [ ] E2E thủ công: curl ... → kết quả ...

## Đã đọc
- [ ] EXTENDING.md §8 (checklist)
- [ ] Liên quan tài liệu nào trong docs/dev/
```

---

## Kênh dev & liên hệ

- **Chat dev hằng ngày**: `#tokinarc-dev` (Slack/Discord) — hỏi nhanh, báo blocker,
  dán log lỗi trước khi mở issue. Mọi dev mới join channel này ngay ở ngày đầu.
- **PR review**: tag tech lead trong PR; review bắt buộc trước khi merge lên `main`.
- **Khẩn cấp production**: alert manager + kiểm tra `infra/scripts/backup.sh` xem WAL còn không.

> ⚠️ Onboarding: nếu chưa có quyền vào `#tokinarc-dev`, nhờ tech lead invite.
> Channel là nơi chính để hỏi đáp — ưu tiên hơn DM để cả team thấy được context.
