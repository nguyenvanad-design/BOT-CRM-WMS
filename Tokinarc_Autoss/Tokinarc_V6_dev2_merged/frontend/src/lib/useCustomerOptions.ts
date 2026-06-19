/**
 * Tokinarc frontend — src/lib/useCustomerOptions.ts
 * Lấy danh sách KH (gom toàn bộ trang) để đổ vào <select> trong form.
 * Cache lâu vì danh sách KH ít đổi trong 1 phiên.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchAll } from '@/lib/list'
import type { Customer } from '@/lib/types'
import type { Option } from '@/components/form'

export function useCustomerOptions() {
  const q = useQuery({
    queryKey: ['customer-options'],
    queryFn: () => fetchAll<Customer>('/crm/customers/'),
    staleTime: 5 * 60 * 1000,
  })
  const options: Option[] = (q.data?.items ?? []).map((c) => ({
    value: c.id,
    label: `${c.code} — ${c.name}`,
  }))
  return { options, isLoading: q.isLoading, isError: q.isError }
}

/** Đổi map nhãn enum {value: label} → Option[] cho <select>. */
export function optionsFromLabels(map: Record<string, string>): Option[] {
  return Object.entries(map).map(([value, label]) => ({ value, label }))
}

/** Danh sách cơ hội (để gắn hoạt động/visit vào đúng thương vụ). */
interface OppLite { id: string; title: string; customer: string; customer_name: string }
export function useOpportunityOptions() {
  const q = useQuery({
    queryKey: ['opportunity-options'],
    queryFn: () => fetchAll<OppLite>('/crm/opportunities/'),
    staleTime: 5 * 60 * 1000,
  })
  return { opps: q.data?.items ?? [], isLoading: q.isLoading }
}
