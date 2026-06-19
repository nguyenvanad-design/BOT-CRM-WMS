/**
 * Tokinarc frontend — src/lib/analytics.ts
 * Gọi các endpoint analytics (Django, manager+ only) cho CEO dashboard.
 */
import { api } from '@/lib/api'
import type {
  KpiOverview, RevenueMonth, SegmentRevenue, PipelineForecastRow,
  InventoryValue, DebtAgingItem,
} from '@/lib/types'

export const getKpi = async () =>
  (await api.get<KpiOverview>('/analytics/kpi/overview/')).data

export const getRevenueMonthly = async () =>
  (await api.get<RevenueMonth[]>('/analytics/revenue/monthly/')).data

export const getRevenueBySegment = async () =>
  (await api.get<SegmentRevenue[]>('/analytics/revenue/by-segment/')).data

export const getForecast = async () =>
  (await api.get<PipelineForecastRow[]>('/analytics/forecast/pipeline/')).data

export const getInventoryValue = async (warehouse?: string) =>
  (await api.get<InventoryValue>('/analytics/inventory/value/', {
    params: warehouse ? { warehouse } : undefined,
  })).data

export const getDebtAging = async () =>
  (await api.get<{ count: number; results: DebtAgingItem[] }>('/analytics/debt-aging/')).data

export interface ExecSummary {
  summary: string
  metrics: Record<string, number | string | null>
  generated_by: 'ai' | 'template'
}
export const getExecSummary = async () =>
  (await api.get<ExecSummary>('/analytics/assistant/summary/')).data
