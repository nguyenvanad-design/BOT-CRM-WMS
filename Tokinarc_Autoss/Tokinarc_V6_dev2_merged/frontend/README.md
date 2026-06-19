# Tokinarc Frontend (React + Vite + TS)

Slice 1: **Login + Khách hàng** gọi API thật.

## Chạy dev
```bash
npm install
npm run dev          # http://localhost:5173
```
Dev server proxy `/api` → `http://localhost:8000` (Django). Đảm bảo backend đang chạy.

## Cấu hình
- `VITE_API_BASE` (mặc định `/api/v1`) — đổi nếu backend ở host khác.
- JWT lưu localStorage: `tokinarc_access`, `tokinarc_refresh`, `tokinarc_user`.
- Tự refresh token khi gặp 401; refresh fail → về /login.

## Cấu trúc
```
src/
  lib/
    api.ts          # axios + JWT interceptor + auto-refresh
    types.ts        # shape khớp serializer backend
    auth/store.ts   # zustand: login/logout/hasRole
  components/Layout.tsx   # sidebar + topbar + logout
  pages/
    Login.tsx       # POST /auth/login/
    Customers.tsx   # GET /crm/customers/ (search, phân trang)
  App.tsx           # router + route guard
```

## Build
```bash
npm run build       # tsc --noEmit && vite build → dist/
```

## Mở rộng (slice tiếp theo)
- Thêm trang: tạo `pages/X.tsx`, thêm `<Route>` trong App.tsx + link trong Layout.
- Ẩn/hiện menu theo role: dùng `useAuth().hasRole('manager','admin')`.
- Nhớ: phân quyền THẬT ở backend; frontend chỉ ẩn UI cho gọn.
