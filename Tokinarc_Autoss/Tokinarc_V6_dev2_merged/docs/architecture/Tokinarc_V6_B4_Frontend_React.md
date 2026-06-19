# TOKINARC — V6.B.4 · Frontend React

**Vite + React 18 + TS + TanStack Query + Zustand + shadcn/ui · chat widget confidence/warnings · port 3 HTML demo**

Phụ thuộc: V6.B.1 (Topology), V6.B.3 (API contract)

Ngày soạn: 16/06/2026 · Phiên bản: 1.0

---

## Mục lục

1. Stack FE
2. Cấu trúc thư mục
3. API client & auth interceptor
4. State management
5. UI theme tokens (3 màu module)
6. Routing & layout
7. Form validation
8. Migration plan — 3 demo → React
9. Chat widget (SSE + confidence/warnings)
10. Build, deploy

---

## 1. Stack FE

| Package | Version | Vai trò |
| --- | --- | --- |
| react, react-dom | 18.3 | UI |
| react-router-dom | 6.x | routing |
| typescript | 5.x | type safety |
| vite | 5.x | dev + bundler |
| @tanstack/react-query | 5.x | server state |
| zustand | 4.x | client state |
| axios | 1.x | HTTP + interceptor |
| react-hook-form + zod + @hookform/resolvers | 7/3/3 | form validation |
| tailwindcss | 3.x | CSS |
| @radix-ui/* + class-variance-authority + shadcn | latest | component |
| lucide-react | latest | icon |
| recharts | 2.x | chart CEO |
| date-fns | 3.x | date util VN |
| sonner | latest | toast |
| react-markdown + remark-gfm | latest | render bot response |
| @microsoft/fetch-event-source | 2.x | SSE client chat |

Không dùng: Redux (TanStack + Zustand đủ), Next.js (app nội bộ, không cần SSR), MUI/AntD (khó match dark theme), moment/dayjs (date-fns nhẹ hơn).

---

## 2. Cấu trúc thư mục

```
frontend/
├── package.json  vite.config.ts  tsconfig.json  tailwind.config.ts  index.html
├── .env.development   # VITE_API_BASE=http://localhost:8000
├── .env.production    # VITE_API_BASE=https://app.tokinarc.vn  (internal gateway)
└── src/
    ├── main.tsx  App.tsx  routes.tsx
    ├── lib/
    │   ├── api/ {client,types,auth,crm,sales,wms,analytics,catalog,chat,storage}.ts
    │   ├── auth/ {token,jwt,guard}.tsx
    │   ├── theme/ {tokens,ThemeProvider}.ts(x)
    │   ├── format/ {money,date,relative}.ts
    │   └── utils.ts
    ├── stores/ {auth,ui,chat}.ts            # Zustand
    ├── components/
    │   ├── ui/                              # shadcn copied
    │   ├── shared/ {AppShell,Sidebar,PageHeader,DataTable,KpiCard,BarH,Donut,
    │   │            Waterfall,EmptyState,ConfirmDialog,FormField,WarehouseSwitcher}.tsx
    │   ├── crm/  {CustomerCard,CustomerCard360Modal,QuoteForm,ContractForm,
    │   │          LeadQualifyButton,PipelineKanban,TicketRow}.tsx
    │   ├── wms/  {InventoryTable,ZoneOverview,PickListPanel,BarcodeScanInput,RackGrid}.tsx
    │   ├── ceo/  {KpiOverview,RevenueChart,DebtAgingTable,ProfitWaterfall,
    │   │          InstalledBaseTable,ExecutiveSummary}.tsx
    │   └── chat/ {ChatPanel,MessageList,StreamingMessage,ConfidenceBadge}.tsx
    └── pages/ login/  crm/(14)  wms/(14)  ceo/(13)
```

`WarehouseSwitcher` mới: đọc `/api/wms/warehouses/`, **ẩn khi count===1** (auto chọn kho đó), hiện dropdown khi ≥2.

---

## 3. API client & auth interceptor

```ts
// src/lib/api/client.ts
import axios from 'axios';
import { tokenStore } from '../auth/token';

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use(cfg => {
  const t = tokenStore.access();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

let isRefreshing = false;
let waitQueue: Array<(t: string) => void> = [];

api.interceptors.response.use(
  r => r,
  async err => {
    const { response, config } = err;
    if (response?.status === 401 && response.data?.code === 'AUTH_TOKEN_EXPIRED' && !config._retry) {
      config._retry = true;
      if (isRefreshing) {
        return new Promise(res => waitQueue.push(t => {
          config.headers.Authorization = `Bearer ${t}`; res(api(config));
        }));
      }
      isRefreshing = true;
      try {
        const { data } = await axios.post(`${import.meta.env.VITE_API_BASE}/api/auth/refresh/`,
          { refresh: tokenStore.refresh() });
        tokenStore.set(data.access, data.refresh);
        waitQueue.forEach(fn => fn(data.access)); waitQueue = [];
        config.headers.Authorization = `Bearer ${data.access}`;
        return api(config);
      } catch (e) {
        tokenStore.clear(); window.location.href = '/login'; throw e;
      } finally { isRefreshing = false; }
    }
    throw err;
  });
```

`token.ts`: access in-memory (biến module) + refresh ở localStorage (để reload không mất phiên). `jwt.ts`: decode đọc role (không verify — chỉ Django/sidecar verify).

---

## 4. State management

- **TanStack Query**: tất cả server state (list KH, đơn, tồn kho, KPI). Key theo resource + filter. `staleTime` 30s cho list, 5m cho catalog.
- **Zustand**: client state — `auth` (currentUser), `ui` (sidebarOpen, theme, **currentWarehouse**), `chat` (session_id, messages).
- Mutation (tạo BG, chuyển HĐ) → `invalidateQueries` resource liên quan.

---

## 5. UI theme tokens

Accent đổi theo module qua `body[data-module]` (AppShell set theo route prefix):

```css
body[data-module='crm'] { --accent: 22 86% 49%;  } /* orange #e05c1b */
body[data-module='wms'] { --accent: 199 89% 48%; } /* blue   #0ea5e9 */
body[data-module='ceo'] { --accent: 41 75% 57%;  } /* gold   #e0b341 */
```

| Module | Background | Accent |
| --- | --- | --- |
| CRM | #0d1117 | #e05c1b |
| WMS | #0b1120 | #0ea5e9 |
| CEO | #0a0e17 | #e0b341 |

---

## 6. Routing & layout

```tsx
export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { element: <RequireAuth><AppShell /></RequireAuth>, children: [
    { index: true, element: <Navigate to="/crm/dashboard" /> },
    { path: '/crm', children: [ /* 14 routes */ ] },
    { path: '/wms', element: <RequireRole roles={['warehouse','manager','admin']}><Outlet/></RequireRole>, children: [ /* 14 */ ] },
    { path: '/ceo', element: <RequireRole roles={['manager','admin']}><Outlet/></RequireRole>, children: [ /* 13 */ ] },
  ]},
]);
```

`RequireAuth` kiểm token + redirect login. `RequireRole` kiểm role → "403 — không có quyền".

> Lưu ý 2-gateway: FE nhân viên trỏ `VITE_API_BASE` = internal gateway. **Chat UI cho khách** (Zalo/web) là build/app riêng trỏ public gateway, chỉ có ChatPanel + login — không bundle CRM/WMS/CEO. (Có thể tách entry `main.customer.tsx` trong cùng repo.)

---

## 7. Form validation

```tsx
const quoteSchema = z.object({
  customer: z.string().min(1, 'Chọn khách hàng'),
  due_date: z.string().refine(d => new Date(d) > new Date(), 'Hạn BG phải trong tương lai'),
  lines: z.array(z.object({
    part: z.string().optional(), torch: z.string().optional(),
    qty: z.number().int().positive('SL phải > 0'),
    unit_price: z.number().nonnegative(),
    discount_pct: z.number().min(0).max(100),
  })).min(1, 'Cần ít nhất 1 dòng SP'),
});
type QuoteFormData = z.infer<typeof quoteSchema>;
```

Quote và Contract dùng chung `QuoteForm` (cùng shape line items, 4B.4). Prop `mode:'quote'|'contract'` đổi label nút + endpoint.

---

## 8. Migration plan — 3 demo → React (1 FE dev, 3–4 tuần)

**Tuần 1** — hạ tầng + auth + AppShell + CRM core 6 trang:
| # | Route | Endpoint |
| --- | --- | --- |
| login | /login | /api/auth/login |
| dashboard | /crm/dashboard | /api/crm/customers,/opportunities,/tickets |
| customers | /crm/customers | /api/crm/customers |
| leads | /crm/leads | /api/crm/leads |
| quotes | /crm/quotes | /api/crm/quotes |
| contracts | /crm/contracts | /api/sales/orders |
| pipeline | /crm/pipeline | /api/crm/opportunities |

Deliverable T1: login → xem KH → qualify lead → tạo BG → chuyển HĐ (demo end-to-end CRM).

**Tuần 2** — CRM còn lại (opportunities, contacts, visits + GPS + upload, activities, tickets, warranty, products, AI chat).
**Tuần 3** — WMS 14 trang (pattern lặp; đặc biệt: BarcodeScan qua `@zxing/library` hoặc USB scanner; RackGrid SVG từ `/api/wms/bins/?warehouse=`).
**Tuần 4** — CEO 13 trang (mỗi trang ~4 KPI + 2-3 chart Recharts + 1 table; phức tạp nhất: Profit waterfall, Cashflow dual-bar, Debt aging, Forecast multi-scenario).
**Polish & ship** — E2E 3 flow (BG→HĐ; nhập→xuất kho; CEO KPI); a11y; bundle <500KB gz; error boundary + Sentry (optional).

---

## 9. Chat widget (SSE + confidence/warnings)

`ChatPanel` floating góc dưới phải (sau login).

```ts
// lib/api/chat.ts
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { tokenStore } from '../auth/token';

export async function streamChat(query: string, sessionId: string,
  onChunk: (t: string) => void,
  onMeta: (m: { confidence: number; tier: string; warnings: string[] }) => void,
  onDone: () => void) {
  await fetchEventSource(`${import.meta.env.VITE_API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${tokenStore.access()}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, session_id: sessionId }),
    onmessage(ev) {
      const e = JSON.parse(ev.data);
      if (e.type === 'text') onChunk(e.chunk);
      if (e.type === 'done') { onMeta({ confidence: e.confidence, tier: e.tier, warnings: e.warnings || [] }); onDone(); }
    },
  });
}
```

`ConfidenceBadge` render theo tier (B.3 §4.2): high → ẩn; med → badge "cần kiểm tra"; low → banner cảnh báo. `warnings[]` hiện dưới message. Khi bot gợi ý action ("tạo BG nháp") → kèm button navigate sang form prefilled.

---

## 10. Build, deploy

```
# .env.production
VITE_API_BASE=https://app.tokinarc.vn      # internal gateway
VITE_APP_TITLE=Tokinarc
```

```bash
npm run build      # → dist/
```

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./ && RUN npm ci
COPY . . && RUN npm run build
FROM nginx:1.26-alpine
COPY --from=build /app/dist /usr/share/nginx/html
```

FE chạy như service `frontend` phục vụ static; **internal nginx** route `/api/*` → Django/sidecar, `/` → FE. Code quality: ESLint + Prettier, TS strict, husky + lint-staged, CI `tsc --noEmit`.
