/**
 * Tokinarc frontend — src/lib/useWmsOptions.ts
 * Option dùng chung cho form WMS: kho, và mặt hàng (part + torch gộp, mã hóa
 * tiền tố 'part:' / 'torch:' để biết loại khi submit).
 */
import { useQuery } from '@tanstack/react-query'
import { fetchAll } from '@/lib/list'
import type { Warehouse } from '@/lib/types'
import type { Option } from '@/components/form'

interface PartLite { tokin_part_no: string; display_name_vi: string }
interface TorchLite { model_code: string; display_name_vi: string }

export function useWarehouseOptions() {
  const q = useQuery({
    queryKey: ['wms-wh-opt'],
    queryFn: () => fetchAll<Warehouse>('/wms/warehouses/'),
    staleTime: 5 * 60 * 1000,
  })
  const options: Option[] = (q.data?.items ?? []).map((w) => ({ value: w.id, label: `${w.code} — ${w.name}` }))
  return { options, isLoading: q.isLoading }
}

export function useItemOptions() {
  const parts = useQuery({
    queryKey: ['catalog-parts-opt'],
    queryFn: () => fetchAll<PartLite>('/catalog/parts/'),
    staleTime: 5 * 60 * 1000,
  })
  const torches = useQuery({
    queryKey: ['catalog-torches-opt'],
    queryFn: () => fetchAll<TorchLite>('/catalog/torches/'),
    staleTime: 5 * 60 * 1000,
  })
  const options: Option[] = [
    ...(torches.data?.items ?? []).map((t) => ({
      value: `torch:${t.model_code}`, label: `[Súng] ${t.model_code} — ${t.display_name_vi}`,
    })),
    ...(parts.data?.items ?? []).map((p) => ({
      value: `part:${p.tokin_part_no}`, label: `${p.tokin_part_no} — ${p.display_name_vi}`,
    })),
  ]
  return { options, isLoading: parts.isLoading || torches.isLoading }
}

/** Tách 'part:XXX' / 'torch:YYY' → { part?, torch? } cho payload. */
export function splitItem(encoded: string): { part?: string; torch?: string } {
  if (encoded.startsWith('torch:')) return { torch: encoded.slice(6) }
  if (encoded.startsWith('part:')) return { part: encoded.slice(5) }
  return {}
}
