/**
 * Tokinarc frontend — src/components/Layout.tsx
 * Khung app đa module (CRM + WMS): switcher đổi module, sidebar đổi nav theo
 * module hiện tại (suy từ path). Sidebar là drawer trên mobile. Trợ lý CRM nổi đáy.
 */
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import {
  Flame, LogOut, LayoutDashboard, TrendingUp, Building2,
  Radar, Target, Filter, FileText, ScrollText, MapPin, Phone,
  Ticket as TicketIcon, ShieldCheck, Wrench, Sparkles, Menu, X, Wallet,
  Package, Barcode, History, Inbox, PackageCheck,
  Warehouse, Map as MapIcon, ScanLine, FileBarChart, Crown, Bot, ClipboardCheck, Gauge,
  ShoppingCart, Building, Undo2, CalendarDays, UserCog,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useAuth, isWmsControl, isManager, isAdmin } from '@/lib/auth/store'
import { ChatWidget } from '@/components/ChatWidget'
import { NotificationBell } from '@/components/NotificationBell'
import { ProfileModal } from '@/components/ProfileModal'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Admin', ceo: 'CEO', manager: 'Quản lý', sales: 'Sale',
  warehouse: 'NV Kho', wh_manager: 'Quản lý kho', service: 'Dịch vụ', customer: 'Khách',
}

interface NavItem { to: string; icon: ReactNode; label: string; badge?: number; ctrl?: boolean; mgr?: boolean }
interface NavGroup { group: string; items: NavItem[] }

const CRM_NAV: NavGroup[] = [
  { group: 'Tổng quan', items: [
    { to: '/dashboard', icon: <LayoutDashboard size={16} />, label: 'Dashboard' },
    { to: '/forecast', icon: <TrendingUp size={16} />, label: 'Forecast', mgr: true },
  ]},
  { group: 'Khách hàng', items: [
    { to: '/customers', icon: <Building2 size={16} />, label: 'Khách hàng' },
    { to: '/leads', icon: <Radar size={16} />, label: 'Leads' },
    { to: '/opportunities', icon: <Target size={16} />, label: 'Opportunity' },
    { to: '/pipeline', icon: <Filter size={16} />, label: 'Pipeline' },
  ]},
  { group: 'Bán hàng', items: [
    { to: '/quotes', icon: <FileText size={16} />, label: 'Báo giá' },
    { to: '/orders', icon: <ShoppingCart size={16} />, label: 'Đơn bán' },
    { to: '/contracts', icon: <ScrollText size={16} />, label: 'Hợp đồng' },
    { to: '/invoices', icon: <FileText size={16} />, label: 'Hóa đơn (MISA)', mgr: true },
    { to: '/receivables', icon: <Wallet size={16} />, label: 'Công nợ', mgr: true },
  ]},
  { group: 'Hoạt động', items: [
    { to: '/my-activity', icon: <CalendarDays size={16} />, label: 'Nhật ký của tôi' },
    { to: '/visits', icon: <MapPin size={16} />, label: 'Visit Report' },
    { to: '/activities', icon: <Phone size={16} />, label: 'Hoạt động' },
  ]},
  { group: 'Dịch vụ', items: [
    { to: '/tickets', icon: <TicketIcon size={16} />, label: 'Service Ticket' },
    { to: '/warranty', icon: <ShieldCheck size={16} />, label: 'Bảo hành' },
    { to: '/procedures', icon: <Wrench size={16} />, label: 'Lắp đặt / Sửa chữa' },
    { to: '/returns', icon: <Undo2 size={16} />, label: 'Trả hàng (RMA)' },
  ]},
  { group: 'Sản phẩm & AI', items: [
    { to: '/products', icon: <Wrench size={16} />, label: 'Sản phẩm' },
    { to: '/ai', icon: <Sparkles size={16} />, label: 'AI Gợi ý' },
  ]},
]

const WMS_NAV: NavGroup[] = [
  { group: 'Tổng quan', items: [
    { to: '/wms/dashboard', icon: <LayoutDashboard size={16} />, label: 'Dashboard' },
  ]},
  { group: 'Tồn kho', items: [
    { to: '/wms/inventory', icon: <Package size={16} />, label: 'Tồn kho' },
    { to: '/wms/trace', icon: <Barcode size={16} />, label: 'Truy xuất (Serial/Lô)' },
    { to: '/wms/movements', icon: <History size={16} />, label: 'Lịch sử kho' },
  ]},
  { group: 'Mua hàng', items: [
    { to: '/purchasing/orders', icon: <ShoppingCart size={16} />, label: 'Đơn mua', ctrl: true },
    { to: '/purchasing/suppliers', icon: <Building size={16} />, label: 'Nhà cung cấp', ctrl: true },
  ]},
  { group: 'Nhập kho', items: [
    { to: '/wms/asn', icon: <Inbox size={16} />, label: 'ASN' },
    { to: '/wms/inbound', icon: <PackageCheck size={16} />, label: 'Nhập kho' },
  ]},
  { group: 'Xuất kho', items: [
    { to: '/wms/outbound', icon: <PackageCheck size={16} />, label: 'Xuất kho' },
  ]},
  { group: 'Cấu hình & công cụ', items: [
    { to: '/wms/warehouses', icon: <Warehouse size={16} />, label: 'Kho & vị trí' },
    { to: '/wms/map', icon: <MapIcon size={16} />, label: 'Bản đồ kho' },
    { to: '/wms/scan', icon: <ScanLine size={16} />, label: 'Quét mã' },
    { to: '/wms/cycle-count', icon: <ClipboardCheck size={16} />, label: 'Kiểm kê' },
    { to: '/wms/ops-kpi', icon: <Gauge size={16} />, label: 'KPI vận hành', ctrl: true },
    { to: '/wms/reports', icon: <FileBarChart size={16} />, label: 'Báo cáo' },
  ]},
]

const CEO_NAV: NavGroup[] = [
  { group: 'Phê duyệt', items: [
    { to: '/ceo/approvals', icon: <ClipboardCheck size={16} />, label: 'Cần duyệt' },
  ]},
  { group: 'Tổng quan', items: [
    { to: '/ceo/overview', icon: <Crown size={16} />, label: 'Bảng điều hành' },
    { to: '/ceo/ai-summary', icon: <Bot size={16} />, label: 'AI Summary' },
  ]},
  { group: 'Tài chính', items: [
    { to: '/ceo/revenue', icon: <TrendingUp size={16} />, label: 'Doanh thu' },
    { to: '/ceo/debt', icon: <Wallet size={16} />, label: 'Công nợ' },
  ]},
  { group: 'Kinh doanh', items: [
    { to: '/ceo/forecast', icon: <Sparkles size={16} />, label: 'Forecast' },
  ]},
  { group: 'Vận hành', items: [
    { to: '/ceo/inventory', icon: <Package size={16} />, label: 'Tồn kho' },
  ]},
]

const SERVICE_NAV: NavGroup[] = [
  { group: 'Dịch vụ', items: [
    { to: '/tickets', icon: <TicketIcon size={16} />, label: 'Hàng chờ Ticket' },
    { to: '/warranty', icon: <ShieldCheck size={16} />, label: 'Bảo hành' },
    { to: '/returns', icon: <Undo2 size={16} />, label: 'Trả hàng (RMA)' },
  ]},
  { group: 'Tra cứu', items: [
    { to: '/procedures', icon: <Wrench size={16} />, label: 'Lắp đặt / Sửa chữa' },
    { to: '/customers', icon: <Building2 size={16} />, label: 'Khách hàng' },
    { to: '/products', icon: <Wrench size={16} />, label: 'Sản phẩm' },
  ]},
]

const ADMIN_NAV: NavGroup[] = [
  { group: 'Hệ thống', items: [
    { to: '/admin/users', icon: <UserCog size={16} />, label: 'Người dùng & quyền' },
  ]},
]

// Cô lập tab theo vai trò: mỗi người chỉ thấy "khu" của mình (admin thấy tất cả).
//   CRM  = phòng kinh doanh (sale + manager kinh doanh + dịch vụ)
//   WMS  = phòng kho (NV kho + QL kho)
//   CEO  = điều hành (ceo)
//   Quản trị = admin
const MODULES = [
  { key: 'crm', label: 'CRM', nav: CRM_NAV, home: '/dashboard', roles: ['sales', 'manager'] },
  { key: 'wms', label: 'WMS', nav: WMS_NAV, home: '/wms/dashboard', roles: ['warehouse', 'wh_manager'] },
  { key: 'service', label: 'Dịch vụ', nav: SERVICE_NAV, home: '/tickets', roles: ['service'] },
  { key: 'ceo', label: 'CEO', nav: CEO_NAV, home: '/ceo/overview', roles: ['ceo'] },
  { key: 'admin', label: 'Quản trị', nav: ADMIN_NAV, home: '/admin/users', roles: ['admin'] },
] as const

export function Layout() {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)

  const role = user?.role
  const canCtrl = isWmsControl(role)
  const canMgr = isManager(role)
  const navVisible = (it: NavItem) => (!it.ctrl || canCtrl) && (!it.mgr || canMgr)
  // Admin thấy MỌI tab; vai trò khác chỉ thấy tab của mình.
  const visibleModules = MODULES.filter((m) =>
    isAdmin(user) ? true : (!!role && (m.roles as readonly string[]).includes(role)))
  const pathKey = loc.pathname.startsWith('/wms') || loc.pathname.startsWith('/purchasing') ? 'wms'
    : loc.pathname.startsWith('/ceo') ? 'ceo'
    : loc.pathname.startsWith('/admin') ? 'admin' : 'crm'
  // Nếu path thuộc tab user KHÔNG có (vd manager mở trang tài chính /ceo/*) → hiện nav tab của mình.
  const moduleKey = visibleModules.some((m) => m.key === pathKey) ? pathKey : (visibleModules[0]?.key ?? 'crm')
  const current = MODULES.find((m) => m.key === moduleKey) ?? MODULES[0]

  const onLogout = async () => { await logout(); nav('/login', { replace: true }) }
  const closeDrawer = () => setMobileOpen(false)

  return (
    <div className="h-screen flex overflow-hidden">
      {mobileOpen && <div className="fixed inset-0 bg-black/60 z-30 lg:hidden" onClick={closeDrawer} />}

      <aside
        className={`bg-ink-2 border-r border-line flex flex-col w-60 shrink-0 overflow-y-auto
                    fixed inset-y-0 left-0 z-40 transition-transform duration-200
                    lg:static lg:translate-x-0
                    ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`}
      >
        <div className="h-14 flex items-center gap-2 px-4 border-b border-line shrink-0">
          <div className="w-8 h-8 rounded-lg bg-flame grid place-items-center">
            <Flame className="text-white" size={17} />
          </div>
          <div className="leading-tight flex-1">
            <div className="font-bold text-sm tracking-tight">Tokinarc</div>
            <div className="text-[10px] text-txt-2">{current.label}</div>
          </div>
          <button className="lg:hidden text-txt-2 hover:text-txt p-1" onClick={closeDrawer} aria-label="Đóng menu">
            <X size={18} />
          </button>
        </div>

        {/* Module switcher */}
        <div className="flex gap-1 p-2 border-b border-line">
          {visibleModules.map((m) => (
            <button
              key={m.key}
              onClick={() => { nav(m.home); closeDrawer() }}
              className={`flex-1 text-xs font-medium rounded-md py-1.5 transition-colors ${
                m.key === moduleKey ? 'bg-flame/15 text-flame' : 'text-txt-2 hover:bg-ink-3 hover:text-txt'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        <nav className="flex-1 p-2">
          {current.nav.filter((g) => g.items.some(navVisible)).map((g) => (
            <div key={g.group}>
              <div className="text-[10px] uppercase tracking-wide text-txt-2 font-semibold px-2.5 pt-3 pb-1">
                {g.group}
              </div>
              {g.items.filter(navVisible).map((it) => (
                <SideLink key={it.to} to={it.to} icon={it.icon} badge={it.badge} onClick={closeDrawer}>
                  {it.label}
                </SideLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 bg-ink-2 border-b border-line flex items-center gap-3 px-4 sm:px-5 shrink-0">
          <button className="lg:hidden text-txt-2 hover:text-txt -ml-1 p-1" onClick={() => setMobileOpen(true)} aria-label="Mở menu">
            <Menu size={20} />
          </button>
          <div className="flex-1" />
          <NotificationBell />
          <button onClick={() => setProfileOpen(true)} title="Tài khoản của tôi"
            className="text-right leading-tight hover:opacity-80 transition-opacity">
            <div className="text-sm font-medium truncate max-w-[40vw]">{user?.display_name || user?.username}</div>
            <div className="text-xs text-txt-2">{ROLE_LABEL[user?.role ?? ''] ?? user?.role}</div>
          </button>
          <button
            onClick={onLogout}
            className="flex items-center gap-1.5 text-sm text-txt-2 hover:text-txt
                       border border-line rounded-md px-2.5 sm:px-3 py-1.5 transition-colors"
          >
            <LogOut size={15} /> <span className="hidden sm:inline">Đăng xuất</span>
          </button>
        </header>
        <main className="flex-1 min-h-0 p-4 sm:p-6 overflow-auto">
          <Outlet />
        </main>
        <ChatWidget />
      </div>
      <ProfileModal open={profileOpen} onClose={() => setProfileOpen(false)} />
    </div>
  )
}

function SideLink({ to, icon, badge, onClick, children }: {
  to: string; icon: ReactNode; badge?: number; onClick?: () => void; children: ReactNode
}) {
  return (
    <NavLink
      to={to}
      onClick={onClick}
      className={({ isActive }) =>
        `flex items-center gap-2.5 px-2.5 py-2 rounded-md text-[13px] transition-colors mb-0.5 ${
          isActive ? 'bg-flame/15 text-flame font-semibold' : 'text-txt-2 hover:text-txt hover:bg-ink-3/50'
        }`
      }
    >
      <span className="w-4 grid place-items-center">{icon}</span>
      <span className="flex-1">{children}</span>
      {badge ? <span className="bg-flame text-white rounded-full text-[10px] px-1.5 leading-4">{badge}</span> : null}
    </NavLink>
  )
}
