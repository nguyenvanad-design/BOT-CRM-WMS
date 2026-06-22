/**
 * Tokinarc frontend — src/App.tsx
 * Router + route guard. Chưa đăng nhập → /login. Đã đăng nhập → layout + trang.
 * Slice CRM: Dashboard, Customers, Leads, Opportunity, Pipeline, Quotes, Visits, Tickets
 * (nối API thật). Các mục chưa có backend → ComingSoon (không bịa data).
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from '@/lib/auth/store'
import { LoginPage } from '@/pages/Login'
import { Layout } from '@/components/Layout'
import { DashboardPage } from '@/pages/crm/Dashboard'
import { CustomersPage } from '@/pages/Customers'
import { Customer360Page } from '@/pages/crm/Customer360'
import { LeadsPage } from '@/pages/crm/Leads'
import { OpportunitiesPage } from '@/pages/crm/Opportunities'
import { OpportunityDetailPage } from '@/pages/crm/OpportunityDetail'
import { PipelinePage } from '@/pages/crm/Pipeline'
import { QuotesPage } from '@/pages/crm/Quotes'
import { ReceivablesPage } from '@/pages/crm/Receivables'
import { InvoicesPage } from '@/pages/crm/Invoices'
import { OrdersPage } from '@/pages/crm/Orders'
import { ReturnsPage } from '@/pages/crm/Returns'
import { MyActivityPage } from '@/pages/crm/MyActivity'
import { VisitsPage } from '@/pages/crm/Visits'
import { TicketsPage } from '@/pages/crm/Tickets'
import { ProductsPage } from '@/pages/crm/Products'
import { CrmForecastPage } from '@/pages/crm/Forecast'
import { WarrantyPage } from '@/pages/crm/Warranty'
import { ScanPage } from '@/pages/wms/Scan'
import { WmsCycleCountPage } from '@/pages/wms/CycleCount'
import { WmsLotsPage } from '@/pages/wms/Lots'
import { WmsOpsKpiPage } from '@/pages/wms/OpsKpi'
import { PurchaseOrdersPage } from '@/pages/purchasing/PurchaseOrders'
import { SuppliersPage } from '@/pages/purchasing/Suppliers'
import { WarehouseMapPage } from '@/pages/wms/WarehouseMap'
import { WmsReportsPage } from '@/pages/wms/Reports'
import { ContactsPage } from '@/pages/crm/Contacts'
import { ContractsPage } from '@/pages/crm/Contracts'
import { ActivitiesPage } from '@/pages/crm/Activities'
import { AIHubPage } from '@/pages/crm/AIHub'
import { WmsDashboardPage } from '@/pages/wms/Dashboard'
import { InventoryPage } from '@/pages/wms/Inventory'
import { SerialsPage } from '@/pages/wms/Serials'
import { MovementsPage } from '@/pages/wms/Movements'
import { WarehousesPage } from '@/pages/wms/Warehouses'
import { InboundPage } from '@/pages/wms/Inbound'
import { ASNPage } from '@/pages/wms/ASN'
import { OutboundPage } from '@/pages/wms/Outbound'
import { CeoOverviewPage } from '@/pages/ceo/Overview'
import { CeoRevenuePage } from '@/pages/ceo/Revenue'
import { CeoForecastPage } from '@/pages/ceo/Forecast'
import { CeoDebtPage } from '@/pages/ceo/Debt'
import { CeoInventoryPage } from '@/pages/ceo/Inventory'
import { CeoAISummaryPage } from '@/pages/ceo/AISummary'
import { RequireRole } from '@/components/RequireRole'

const MGR = ['manager', 'ceo', 'admin'] as const

function Protected({ children }: { children: React.ReactNode }) {
  const isAuthed = useAuth((s) => s.isAuthed)
  return isAuthed ? <>{children}</> : <Navigate to="/login" replace />
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <Protected>
              <Layout />
            </Protected>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="customers" element={<CustomersPage />} />
          <Route path="customers/:id" element={<Customer360Page />} />
          <Route path="leads" element={<LeadsPage />} />
          <Route path="opportunities" element={<OpportunitiesPage />} />
          <Route path="opportunities/:id" element={<OpportunityDetailPage />} />
          <Route path="pipeline" element={<PipelinePage />} />
          <Route path="quotes" element={<QuotesPage />} />
          <Route path="receivables" element={<ReceivablesPage />} />
          <Route path="orders" element={<OrdersPage />} />
          <Route path="invoices" element={<InvoicesPage />} />
          <Route path="returns" element={<ReturnsPage />} />
          <Route path="my-activity" element={<MyActivityPage />} />
          <Route path="visits" element={<VisitsPage />} />
          <Route path="tickets" element={<TicketsPage />} />

          {/* Đã nối API thật: contacts/contracts/activities (crm), products (catalog),
              warranty (serial WMS); forecast (tính từ opportunities), ai (giới thiệu) */}
          <Route path="forecast" element={<CrmForecastPage />} />
          <Route path="contacts" element={<ContactsPage />} />
          <Route path="contracts" element={<ContractsPage />} />
          <Route path="activities" element={<ActivitiesPage />} />
          <Route path="warranty" element={<WarrantyPage />} />
          <Route path="products" element={<ProductsPage />} />
          <Route path="ai" element={<AIHubPage />} />

          {/* ── WMS ── */}
          <Route path="wms" element={<Navigate to="/wms/dashboard" replace />} />
          <Route path="wms/dashboard" element={<WmsDashboardPage />} />
          <Route path="wms/inventory" element={<InventoryPage />} />
          <Route path="wms/low-stock" element={<InventoryPage lowStock />} />
          <Route path="wms/serials" element={<SerialsPage />} />
          <Route path="wms/movements" element={<MovementsPage />} />
          <Route path="wms/asn" element={<ASNPage />} />
          <Route path="wms/inbound" element={<InboundPage />} />
          <Route path="wms/outbound" element={<OutboundPage />} />
          <Route path="wms/warehouses" element={<WarehousesPage />} />
          <Route path="wms/map" element={<WarehouseMapPage />} />
          <Route path="wms/scan" element={<ScanPage />} />
          <Route path="wms/cycle-count" element={<WmsCycleCountPage />} />
          <Route path="wms/lots" element={<WmsLotsPage />} />
          <Route path="wms/ops-kpi" element={<WmsOpsKpiPage />} />

          {/* ── Mua hàng ── */}
          <Route path="purchasing" element={<Navigate to="/purchasing/orders" replace />} />
          <Route path="purchasing/orders" element={<PurchaseOrdersPage />} />
          <Route path="purchasing/suppliers" element={<SuppliersPage />} />
          <Route path="wms/reports" element={<WmsReportsPage />} />

          {/* ── CEO (manager/admin) ── */}
          <Route path="ceo" element={<Navigate to="/ceo/overview" replace />} />
          <Route path="ceo/overview" element={<RequireRole roles={[...MGR]}><CeoOverviewPage /></RequireRole>} />
          <Route path="ceo/revenue" element={<RequireRole roles={[...MGR]}><CeoRevenuePage /></RequireRole>} />
          <Route path="ceo/forecast" element={<RequireRole roles={[...MGR]}><CeoForecastPage /></RequireRole>} />
          <Route path="ceo/debt" element={<RequireRole roles={[...MGR]}><CeoDebtPage /></RequireRole>} />
          <Route path="ceo/inventory" element={<RequireRole roles={[...MGR]}><CeoInventoryPage /></RequireRole>} />
          <Route path="ceo/ai-summary" element={<RequireRole roles={[...MGR]}><CeoAISummaryPage /></RequireRole>} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
