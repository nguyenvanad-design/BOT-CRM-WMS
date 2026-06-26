/**
 * Tokinarc frontend — src/lib/types.ts
 * Shape khớp serializer backend (UserSerializer, CustomerListSerializer).
 */
export type Role =
  | 'customer' | 'sales' | 'warehouse' | 'wh_manager' | 'service' | 'manager' | 'ceo' | 'admin'

export interface User {
  id: string
  username: string
  display_name: string
  full_name: string
  email: string
  phone: string
  role: Role
  customer: string | null
  is_active: boolean
  is_admin: boolean
  date_joined: string
}

export interface Customer {
  id: string
  code: string
  name: string
  tax_code: string
  segment: string
  region: string
  status: string
  owner: string
  owner_username: string
  contact_count: number
  primary_phone: string
  primary_email: string
  source: string
  notes: string
  created_at: string
  updated_at: string
}

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

// ── Customer detail / 360 (khớp serializers.py) ───────────────────────────
export interface Contact {
  id: string
  full_name: string
  title: string
  phone: string
  email: string
  preferred_channel: string
  is_primary: boolean
  notes: string
  created_at: string
  updated_at: string
}

export interface CrmContact {
  id: string
  customer: string
  customer_name: string
  customer_code: string
  full_name: string
  title: string
  phone: string
  email: string
  preferred_channel: string
  is_primary: boolean
  notes: string
  created_at: string
  updated_at: string
}

export interface CustomerDetail {
  id: string
  code: string
  name: string
  tax_code: string
  segment: string
  region: string
  address: Record<string, unknown>
  status: string
  owner: string
  owner_username: string
  contacts: Contact[]
  notes: string
  created_at: string
  updated_at: string
}

export interface Customer360 {
  customer: CustomerDetail
  open_orders: number
  debt_vnd: string
  open_tickets: number
  last_activity: string | null
}

export type DebtBucket = 'current' | 'd1_30' | 'd31_60' | 'd60p'

export interface Receivable {
  code: string
  customer: string
  customer_id: string
  amount_due: number
  days_overdue: number
  bucket: DebtBucket
  issued_date: string
}

export interface ReceivablesResponse {
  summary: {
    total_due: number
    count: number
    overdue: number
    current: number
    d1_30: number
    d31_60: number
    d60p: number
  }
  results: Receivable[]
}

// ── WMS (khớp apps/wms/serializers.py) ────────────────────────────────────
export interface Warehouse {
  id: string
  code: string
  name: string
  address: Record<string, unknown>
  is_active: boolean
  is_default: boolean
}

export interface InventoryItem {
  id: string
  bin: string
  bin_code: string
  warehouse_code: string
  part: string | null
  torch: string | null
  item_name: string
  category?: string
  qty_on_hand: number
  qty_reserved: number
  qty_available: number
  min_level: number
  updated_at: string
}

export type SerialStatus = 'in_stock' | 'reserved' | 'shipped' | 'sold' | 'returned' | 'scrapped'

export interface SerialNumber {
  id: string
  serial: string
  torch: string
  bin: string | null
  status: SerialStatus
  sold_to_customer: string | null
  sold_order: string
  received_at: string | null
  warranty_until: string | null
}

export type MovementReason = 'inbound' | 'outbound' | 'adjust' | 'transfer' | 'return'

export interface StockMovement {
  id: number
  ts: string
  warehouse: string
  part: string | null
  torch: string | null
  bin: string
  delta: number
  reason: MovementReason
  ref_kind: string
  ref_id: string
  by_username: string
  note: string
}

export type InboundStatus = 'draft' | 'confirmed' | 'partial' | 'putaway' | 'cancelled'

export interface InboundLine {
  id?: string
  part: string | null
  torch: string | null
  part_name?: string
  qty_expected: number
  qty_received: number
  target_bin: string | null
  lot_no: string
  order_idx: number
}

export interface InboundOrder {
  id: string
  code: string
  warehouse: string
  asn: string | null
  status: InboundStatus
  received_at: string | null
  lines: InboundLine[]
  notes: string
  created_at: string
  updated_at: string
}

export type OutboundStatus = 'draft' | 'picking' | 'picked' | 'partial' | 'shipped' | 'cancelled'
export type OutboundRule = 'FIFO' | 'FEFO' | 'NEAREST'

export interface OutboundLine {
  id?: string
  part: string | null
  torch: string | null
  part_name?: string
  qty_ordered: number
  qty_picked: number
  order_idx: number
}

export interface OutboundOrder {
  id: string
  code: string
  warehouse: string
  sales_order_code: string
  customer: string | null
  rule: OutboundRule
  status: OutboundStatus
  shipped_at: string | null
  lines: OutboundLine[]
  notes: string
  created_at: string
  updated_at: string
}

export interface ASN {
  id: string
  code: string
  warehouse: string
  supplier: string
  eta: string | null
  is_arrived: boolean
  notes: string
  created_at: string
  updated_at: string
}

// ── Analytics / CEO (khớp apps/analytics) ─────────────────────────────────
export interface KpiOverview {
  revenue_vnd: number
  collected_vnd: number
  debt_vnd: number
  order_count: number
  customer_count: number
  open_leads: number
}
export interface RevenueMonth { month: string; revenue_vnd: number; orders: number }
export interface SegmentRevenue { segment: string; revenue_vnd: number; orders: number }
export interface PipelineForecastRow { stage: string; weighted_vnd: number; count: number }
export interface InventoryValue { warehouse: string; inventory_value_vnd: number; sku_count: number }
export interface DebtAgingItem {
  code: string
  customer: string
  amount_due: number
  days_overdue: number
  bucket: DebtBucket
}

// ── Catalog (sản phẩm) ────────────────────────────────────────────────────
export interface CatalogPart {
  tokin_part_no: string
  category: string
  ecosystem: string
  current_class: string
  display_name_vi: string
  display_name_en: string
  effective_price_vnd: string | null
  price_display: string
  is_contact_price: boolean
  is_priority_sell: boolean
}

export interface CatalogTorch {
  model_code: string
  family: string
  ecosystem: string
  current_class: string
  cooling: string
  display_name_vi: string
  display_name_en: string
  rated_dc_a: number | null
  duty_cycle_pct: number | null
  effective_price_vnd: string | null
  price_display: string
  is_contact_price: boolean
  is_priority_sell: boolean
}

// ── CRM mở rộng (khớp serializers_ext.py) ─────────────────────────────────

export type LeadStatus = 'new' | 'contacted' | 'qualified' | 'converted' | 'lost'

export interface Lead {
  id: string
  name: string
  company: string
  phone: string
  email: string
  source: string
  source_display?: string
  campaign?: string
  referred_by?: string
  status: LeadStatus
  score: number
  owner: string
  owner_username: string
  converted_customer: string | null
  interest_part: string | null
  interest_part_name: string
  interest_qty: number
  est_value_vnd: number
  notes: string
  created_at: string
  updated_at: string
}

export type OppStage =
  | 'prospect' | 'qualify' | 'proposal' | 'negotiate' | 'won' | 'lost'

export interface Opportunity {
  id: string
  customer: string
  customer_name: string
  title: string
  stage: OppStage
  stage_display: string
  est_value_vnd: string // DecimalField → string
  probability: number
  expected_close: string | null
  owner: string
  owner_username: string
  notes: string
  created_at: string
  updated_at: string
}

export type QuoteStatus =
  | 'draft' | 'sent' | 'pending_ceo' | 'approved' | 'rejected' | 'converted' | 'expired'

export interface TimelineEvent {
  date: string
  kind: 'visit' | 'activity' | 'quote' | 'order' | 'ticket'
  type: string
  title: string
  detail?: string
  next_action?: string
  status?: string
  amount_vnd?: number
  recording_url?: string | null
  recap_file_url?: string | null
  who?: string
}

export interface QuoteLine {
  id?: string
  part_no: string
  part_name: string
  qty: number
  unit_price_vnd: string
  line_total_vnd?: number
}

export interface Quote {
  id: string
  code: string
  customer: string
  customer_name: string
  opportunity: string | null
  status: QuoteStatus
  status_display: string
  due_date: string | null
  valid_until?: string | null
  discount_pct?: string
  payment_terms_note?: string
  subtotal_vnd?: number
  total_vnd: string
  requires_l2: boolean
  margin?: { cost_total_vnd: number; margin_vnd: number; margin_pct: number | null; missing_cost_lines: number } | null
  owner: string
  owner_username: string
  approved_by: string | null
  l1_approved_by: string | null
  l1_approved_at: string | null
  l2_approved_by: string | null
  l2_approved_at: string | null
  contract_order_code: string
  lines: QuoteLine[]
  notes: string
  created_at: string
  updated_at: string
}

export type ContractStatus = 'draft' | 'pending_ceo' | 'rejected' | 'pending_sign' | 'active' | 'expired' | 'cancelled'

export interface Contract {
  id: string
  code: string
  customer: string
  customer_name: string
  quote: string | null
  title: string
  discount_pct?: string
  value_vnd: string
  paid_vnd: string
  debt_vnd: number
  status: ContractStatus
  status_display: string
  start_date: string | null
  end_date: string | null
  owner: string
  owner_username: string
  notes: string
  requires_l2?: boolean
  created_at: string
  updated_at: string
}

export type ActivityType = 'call' | 'email' | 'meeting' | 'zalo' | 'other'

export interface Activity {
  id: string
  customer: string
  customer_name: string
  opportunity: string | null
  activity_type: ActivityType
  activity_type_display: string
  content: string
  activity_date: string
  owner: string
  owner_username: string
  created_at: string
}

export interface Visit {
  id: string
  customer: string
  customer_name: string
  opportunity: string | null
  visit_date: string
  purpose: string
  summary: string
  next_action: string
  gps: Record<string, unknown>
  owner: string
  owner_username: string
  created_at: string
  updated_at: string
}

export type TicketStatus = 'open' | 'in_progress' | 'resolved' | 'closed'
export type TicketPriority = 'low' | 'medium' | 'high' | 'urgent'

export interface Ticket {
  id: string
  code: string
  customer: string
  customer_name: string
  title: string
  description: string
  status: TicketStatus
  status_display: string
  priority: TicketPriority
  priority_display: string
  serial_no: string
  assignee: string | null
  assignee_name?: string
  assignee_username?: string
  resolution?: string
  created_owner: string
  resolved_at: string | null
  created_at: string
  updated_at: string
}
