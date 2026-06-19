# FRONTEND GUIDE — Pattern thêm page mới

> **Stack**: Vite + React 18 + TypeScript + Tailwind + React Query + Zustand + React Hook Form
> **Theme**: thép (`ink/line/txt`) + lửa hàn (`flame`)
> **Đã có**: Login + Customers (slice 1)

---

## Cấu trúc dự án

```
frontend/
├── index.html                ← entry, load Inter + JetBrains Mono fonts
├── vite.config.ts            ← proxy /api → Django :8000
├── tailwind.config.js        ← theme tokens (ink/flame/line/txt/danger/ok/warn)
├── tsconfig.json             ← strict + noUnusedLocals
├── src/
│   ├── main.tsx              ← QueryClient + Toaster
│   ├── App.tsx               ← Router + Protected route guard
│   ├── styles/index.css      ← Tailwind directives + base
│   ├── vite-env.d.ts         ← VITE_API_BASE env type
│   ├── lib/
│   │   ├── api.ts            ← axios + auto-refresh + apiError()
│   │   ├── auth/
│   │   │   ├── store.ts      ← zustand: user, isAuthed, login, logout, hasRole
│   │   │   └── roles.ts      ← (sinh từ dump_roles, chưa có — TODO)
│   │   └── types.ts          ← User, Customer, Paginated<T>, Role
│   ├── components/
│   │   └── Layout.tsx        ← sidebar + topbar + Outlet
│   └── pages/
│       ├── Login.tsx
│       └── Customers.tsx
```

---

## 1. Theme tokens — DÙNG, ĐỪNG ĐỊNH NGHĨA LẠI

Tất cả màu/font đã có trong `tailwind.config.js`:

```js
colors: {
  ink:    { DEFAULT: '#0d1117', 2: '#161b22', 3: '#21262d' },  // nền thép
  line:   '#30363d',                                            // border
  flame:  { DEFAULT: '#e05c1b', hi: '#f97316' },                // accent
  txt:    { DEFAULT: '#e6edf3', 2: '#8b949e' },                 // text + muted
  ok:     '#2ea043', warn: '#d29922', danger: '#f85149',        // status
}
```

**Quy ước class**:

```tsx
// Card / panel
<div className="bg-ink-2 border border-line rounded-lg p-4">

// Subtle background
<div className="bg-ink-3/40 hover:bg-ink-3">

// Text levels
<h1 className="text-txt font-semibold">         {/* primary */}
<p className="text-txt-2 text-sm">              {/* secondary/muted */}
<span className="text-flame font-mono">         {/* highlight */}

// Status badges
<span className="text-ok border-ok/30 bg-ok/10 border rounded-full px-2 py-0.5">
<span className="text-warn ...">
<span className="text-danger ...">

// CTA button
<button className="bg-flame hover:bg-flame-hi text-white font-semibold rounded-md px-4 py-2.5">

// Secondary button
<button className="border border-line hover:bg-ink-3 text-txt rounded-md px-3 py-1.5 text-sm">

// Input
<input className="bg-ink-2 border border-line rounded-md px-3 py-2.5 text-sm focus:border-flame transition-colors">
```

**Đừng**:
- Dùng `bg-gray-800`, `text-orange-500` — sẽ inconsistent
- Tạo color token mới trong `tailwind.config.js` cho 1 page riêng
- Hardcode `style={{color: '#f97316'}}` inline

**Khi nào extend tokens**: khi có 1 brand mới (vd module riêng cho partner) hoặc thêm role màu (`bg-role-sale/10`). Bàn với team trước.

---

## 2. Thêm 1 page mới — Pattern chuẩn

Ví dụ: thêm trang `Quotes` (danh sách báo giá).

### Bước 1: Thêm type khớp backend

```typescript
// src/lib/types.ts
export interface Quote {
  id: string
  code: string
  customer: string
  customer_name: string
  status: 'draft' | 'sent' | 'approved' | 'converted' | 'rejected'
  status_display: string
  due_date: string | null
  total_vnd: string                    // backend trả string (DecimalField)
  owner: string
  owner_username: string
  contract_order_code: string | null
  notes: string
  created_at: string
  updated_at: string
}

export interface QuoteLine {
  id: number
  part_no: string
  part_name: string
  qty: number
  unit_price_vnd: string
  line_total_vnd: string
}

export interface QuoteDetail extends Quote {
  lines: QuoteLine[]
  approved_by: string | null
}
```

**Cách lấy shape chính xác**: gọi backend thật:

```bash
TOKEN=$(...)
curl http://localhost:8000/api/v1/crm/quotes/ -H "Authorization: Bearer $TOKEN" | jq
# Copy các field vào type interface
```

### Bước 2: Tạo page component

```tsx
// src/pages/Quotes.tsx
/**
 * Tokinarc frontend — src/pages/Quotes.tsx
 * Danh sách báo giá. Sale thấy của mình; manager+ thấy hết (lọc ở BE).
 */
import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { FileText, Search } from 'lucide-react'
import { api, apiError } from '@/lib/api'
import type { Quote, Paginated } from '@/lib/types'

const STATUS_STYLE: Record<string, string> = {
  draft:     'text-txt-2 border-line bg-ink-3',
  sent:      'text-warn border-warn/30 bg-warn/10',
  approved:  'text-ok border-ok/30 bg-ok/10',
  converted: 'text-flame border-flame/30 bg-flame/10',
  rejected:  'text-danger border-danger/30 bg-danger/10',
}

async function fetchQuotes(search: string, page: number) {
  const res = await api.get<Paginated<Quote>>('/crm/quotes/', {
    params: { search: search || undefined, page },
  })
  return res.data
}

const fmtVnd = (s: string) => new Intl.NumberFormat('vi-VN').format(Number(s)) + ' ₫'

export function QuotesPage() {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['quotes', search, page],
    queryFn: () => fetchQuotes(search, page),
    placeholderData: keepPreviousData,
  })

  return (
    <div className="max-w-6xl">
      <header className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <FileText size={20} className="text-flame" /> Báo giá
          </h1>
          {data && <p className="text-xs text-txt-2 mt-0.5">{data.count} báo giá</p>}
        </div>
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-txt-2" />
          <input
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
            placeholder="Tìm mã, ghi chú…"
            className="bg-ink-2 border border-line rounded-md pl-9 pr-3 py-2 text-sm w-64 focus:border-flame"
          />
        </div>
      </header>

      <div className="border border-line rounded-lg overflow-hidden bg-ink-2">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-txt-2 border-b border-line">
              <th className="px-4 py-2.5">Mã</th>
              <th className="px-4 py-2.5">Khách hàng</th>
              <th className="px-4 py-2.5">Trạng thái</th>
              <th className="px-4 py-2.5">Hạn</th>
              <th className="px-4 py-2.5 text-right">Tổng tiền</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && <tr><td colSpan={5} className="py-10 text-center text-txt-2">Đang tải…</td></tr>}
            {isError && <tr><td colSpan={5} className="py-10 text-center text-danger">{apiError(error)}</td></tr>}
            {data?.results.map((q) => (
              <tr key={q.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
                <td className="px-4 py-2.5 font-mono text-flame">{q.code}</td>
                <td className="px-4 py-2.5 font-medium">{q.customer_name}</td>
                <td className="px-4 py-2.5">
                  <span className={`text-xs border rounded-full px-2 py-0.5 ${STATUS_STYLE[q.status] ?? STATUS_STYLE.draft}`}>
                    {q.status_display}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-txt-2">{q.due_date ?? '—'}</td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums">{fmtVnd(q.total_vnd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

### Bước 3: Thêm route

```tsx
// src/App.tsx
import { QuotesPage } from '@/pages/Quotes'

// trong <Routes>
<Route path="quotes" element={<QuotesPage />} />
```

### Bước 4: Thêm sidebar link

```tsx
// src/components/Layout.tsx
import { Flame, Users, FileText, LogOut } from 'lucide-react'

// trong <nav>
<SideLink to="/customers" icon={<Users size={17} />}>Khách hàng</SideLink>
<SideLink to="/quotes"    icon={<FileText size={17} />}>Báo giá</SideLink>
```

### Bước 5: Test build

```bash
cd frontend
npm run typecheck                # 0 lỗi
npm run build                    # ~5s
```

Mở `http://localhost:5173/quotes` → page hiện list quotes (rỗng nếu chưa có quote nào).

---

## 3. Permission UI — Hide vs Disable

Khi action chỉ cho 1 role (vd nút "Duyệt" chỉ cho manager):

### Pattern 1: Hide (action không phải brand quan trọng)

```tsx
import { useAuth, isManager } from '@/lib/auth/store'

function QuoteActions({ quote }: { quote: QuoteDetail }) {
  const user = useAuth((s) => s.user)
  return (
    <div className="flex gap-2">
      <button>Sao chép</button>
      {isManager(user?.role) && (
        <button className="bg-flame ...">Duyệt</button>
      )}
    </div>
  )
}
```

### Pattern 2: Disable + tooltip (giáo dục user)

```tsx
<button
  disabled={!isManager(user?.role)}
  title={!isManager(user?.role) ? 'Chỉ quản lý duyệt được báo giá' : ''}
  className="bg-flame disabled:opacity-50 disabled:cursor-not-allowed ..."
>
  Duyệt
</button>
```

> **Quan trọng**: UI permission chỉ là **UX hint**. Backend luôn enforce thật (lớp 3 defense-in-depth). FE không gửi request = không bị 403 chỉ là UX. Sale dùng curl trực tiếp vẫn 403.

---

## 4. Form pattern với react-hook-form + zod

Ví dụ: tạo Customer form.

### Bước 1: Schema validation

```typescript
// src/pages/CustomerCreate.tsx
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'

const schema = z.object({
  code: z.string().regex(/^KH-/, 'Mã KH phải bắt đầu KH-'),
  name: z.string().min(2, 'Tên tối thiểu 2 ký tự'),
  segment: z.enum(['steel', 'auto', 'shipyard', 'fabrication', 'distributor']),
  region: z.string().min(2),
  tax_code: z.string().optional(),
})

type FormData = z.infer<typeof schema>
```

### Bước 2: Form component

```tsx
import { useForm } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'

export function CustomerCreatePage() {
  const qc = useQueryClient()
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema),
  })

  const mutate = useMutation({
    mutationFn: (data: FormData) => api.post('/crm/customers/', data),
    onSuccess: () => {
      toast.success('Đã tạo KH')
      qc.invalidateQueries({ queryKey: ['customers'] })
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <form onSubmit={handleSubmit((d) => mutate.mutate(d))} className="space-y-4 max-w-md">
      <Field label="Mã KH" error={errors.code}>
        <input {...register('code')} className="..." placeholder="KH-0100" />
      </Field>
      <Field label="Tên" error={errors.name}>
        <input {...register('name')} className="..." />
      </Field>
      {/* ... */}
      <button type="submit" disabled={isSubmitting} className="bg-flame ...">
        {isSubmitting ? 'Đang lưu…' : 'Tạo'}
      </button>
    </form>
  )
}

function Field({ label, error, children }: { label: string; error?: { message?: string }; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-txt-2 mb-1.5">{label}</label>
      {children}
      {error && <p className="text-danger text-xs mt-1">{error.message}</p>}
    </div>
  )
}
```

---

## 5. React Query best practices

### queryKey convention

```typescript
// Pattern: [resource, ...filters]
useQuery({ queryKey: ['customers'], ... })                    // list
useQuery({ queryKey: ['customers', search, page], ... })       // list + filter
useQuery({ queryKey: ['customer', id], ... })                  // detail
useQuery({ queryKey: ['customer', id, '360'], ... })           // sub-resource
```

Khi mutate, invalidate đúng key:

```typescript
const mutate = useMutation({
  mutationFn: (data) => api.post('/crm/customers/', data),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ['customers'] })   // refresh list
    // Optional: qc.setQueryData(['customer', newId], newData)  // optimistic update
  },
})
```

### Background refetch

`main.tsx` set:

```typescript
defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } }
```

- `retry: 1` — fail 1 lần thì hiển thị error (không spam backend)
- `refetchOnWindowFocus: false` — tab background không refetch (đỡ tốn API)

Khi cần data luôn fresh (vd Dashboard CEO):

```typescript
useQuery({
  queryKey: ['kpi'],
  queryFn: fetchKpi,
  refetchInterval: 30_000,  // poll 30s
  staleTime: 25_000,
})
```

---

## 6. Auto-refresh JWT — đã có sẵn

`api.ts` đã wire:

1. Mọi request attach `Authorization: Bearer <access>`
2. Nhận 401 → call `/auth/refresh/` 1 lần, retry request
3. Refresh fail → clear token + redirect `/login`
4. Mutex `refreshing` chống concurrent refresh

**Bạn không cần handle 401** trong page — page chỉ catch lỗi business (400, 403, 409).

```typescript
const { error } = useQuery(...)
if (error) toast.error(apiError(error))  // tự dịch ra message tiếng Việt
```

---

## 7. Routing + Protected pages

### Thêm route public (không cần auth)

```tsx
// App.tsx
<Route path="/login" element={<LoginPage />} />
<Route path="/forgot-password" element={<ForgotPasswordPage />} />  {/* public */}

<Route path="/" element={<Protected><Layout /></Protected>}>
  {/* các page cần auth */}
</Route>
```

### Route theo role

```tsx
function ManagerOnly({ children }: { children: React.ReactNode }) {
  const user = useAuth((s) => s.user)
  if (!isManager(user?.role)) {
    return <div className="p-6 text-danger">Bạn không có quyền xem trang này.</div>
  }
  return <>{children}</>
}

// Trong Routes
<Route path="dashboard" element={<ManagerOnly><DashboardPage /></ManagerOnly>} />
```

---

## 8. i18n (i18next) — chưa kích hoạt

`package.json` có cài `i18next` + `react-i18next` nhưng chưa setup. Hiện code đang hardcode tiếng Việt (ổn cho slice 1-3 vì khách hàng đều VN).

Khi cần thêm tiếng Anh (vd dashboard cho đối tác Nhật):

```bash
mkdir -p src/locales/{vi,en}
# src/locales/vi/common.json: { "login.title": "Đăng nhập" }
# src/locales/en/common.json: { "login.title": "Sign in" }
```

Setup `i18next` ở `main.tsx`. Bàn với team trước, không tự enable.

---

## 9. Optimization checklist (production)

Trước khi deploy:

- [ ] `npm run build` → bundle size < 500 KB JS (gzip < 150 KB)
- [ ] Lazy-load page lớn: `const Dashboard = lazy(() => import('./pages/Dashboard'))`
- [ ] Images: prefer SVG, hoặc dùng `<img loading="lazy" />` cho ảnh dưới fold
- [ ] Code split route: vite tự làm khi dùng `lazy()`
- [ ] Tree-shake icon: `import { Users } from 'lucide-react'` (đúng, không `import *`)
- [ ] React Query: `staleTime` đủ dài cho data ít đổi (catalog có thể 10 phút)

---

## 10. Anti-patterns FE

### ❌ Direct fetch không qua `api`

```tsx
// SAI — bỏ qua interceptor (không auth refresh)
useEffect(() => {
  fetch('/api/v1/crm/customers/').then(...)
}, [])
```

**Đúng**: dùng `api` (axios instance đã wire interceptor).

### ❌ State trong component cho data API

```tsx
// SAI — không cache, không invalidate, fetch lại mỗi mount
const [customers, setCustomers] = useState([])
useEffect(() => { fetchCustomers().then(setCustomers) }, [])
```

**Đúng**: React Query `useQuery({queryKey, queryFn})`.

### ❌ Permission check phía FE để "bảo mật"

```tsx
// SAI — không phải security, chỉ là UX hint
if (user.role === 'manager') {
  showSecretFinancialData()
}
```

**Đúng**: gọi API. Nếu role không đủ → backend trả 403 → toast lỗi. UI hide nút chỉ để UX gọn.

### ❌ Tạo color/font/spacing token mới cho 1 chỗ

```tsx
// SAI — gây drift visual
<div style={{ color: '#ff5722', padding: '13px' }}>
```

**Đúng**: dùng `text-flame p-3` (12px gần 13). Nếu không khớp token → bàn với team trước khi extend `tailwind.config.js`.

---

## 11. Debug FE

### TypeScript lỗi sau khi pull

```bash
rm -rf node_modules/.vite      # clear vite cache
npm run typecheck              # tsc strict, sẽ chỉ ra dòng lỗi
```

### Network 401 liên tục

Login lại. Refresh token có thể đã blacklist (vd manager invalidate).

### CORS lỗi khi gọi backend trực tiếp

`vite.config.ts` đã có proxy `/api → :8000`. **Đừng** đổi `VITE_API_BASE` thành URL absolute (vd `http://localhost:8000`) — sẽ vỡ proxy.

### Tailwind class không apply

```bash
# Kiểm tra content path
cat tailwind.config.js | grep content
# Phải là: content: ['./index.html', './src/**/*.{ts,tsx}']
# Nếu thêm folder mới ngoài src → thêm vào content
```

### Bundle quá lớn

```bash
npm run build -- --mode production
# Vite in ra danh sách chunk + size. Nếu chunk vendor > 200KB:
# 1. Lazy load page lớn (recharts, react-markdown)
# 2. Check imports — đừng import default từ lucide-react
```

---

## 12. Roadmap FE

Slice tiếp theo (sau slice 1 Login + Customers):

| Slice | Pages | Endpoint cần |
|---|---|---|
| 2 | Quotes (list, detail, create) | /crm/quotes/ + actions |
| 3 | Chat widget | /chatbot/api/v2/query (cần proxy `/chatbot`) |
| 4 | CEO Dashboard | /analytics/* (manager+) + recharts |
| 5 | Customer 360 detail | /crm/customers/{id}/360/ |
| 6 | WMS Inventory | /wms/inventory/ + bin browse |
| 7 | Service tickets | /crm/tickets/ + resolve workflow |

Khuyến nghị: làm theo thứ tự để pattern giữa các slice nhất quán.
