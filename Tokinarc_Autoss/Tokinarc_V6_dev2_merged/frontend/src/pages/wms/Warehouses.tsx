/**
 * Tokinarc frontend — src/pages/wms/Warehouses.tsx
 * Quản lý KHO & VỊ TRÍ: thêm/sửa kho (code, tên, địa chỉ, mặc định, hoạt động)
 * và quản lý KHU (zone) trong từng kho. Đọc: mọi nhân viên; sửa: QL kho trở lên.
 */
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Warehouse as WarehouseIcon, Star, Plus, Pencil, Layers, Trash2, Boxes } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { fetchAll } from '@/lib/list'
import type { Warehouse } from '@/lib/types'
import { Card, PageHeader, Tag, Button } from '@/components/ui'
import { useAuth, isWmsControl } from '@/lib/auth/store'
import { Modal } from '@/components/Modal'
import { FieldRow, TextInput } from '@/components/form'

interface Zone {
  id: string; warehouse: string; warehouse_code: string
  code: string; name: string; purpose: string; bin_count: number
}

export function WarehousesPage() {
  const qc = useQueryClient()
  const canControl = isWmsControl(useAuth((s) => s.user?.role))
  const [whForm, setWhForm] = useState<{ open: boolean; editing: Warehouse | null }>({ open: false, editing: null })
  const [zoneForm, setZoneForm] = useState<{ open: boolean; warehouse?: Warehouse; editing: Zone | null }>({ open: false, editing: null })
  const [binMgr, setBinMgr] = useState<{ warehouse: Warehouse; zone: Zone } | null>(null)

  const wh = useQuery({ queryKey: ['wms-warehouses'], queryFn: () => fetchAll<Warehouse>('/wms/warehouses/') })
  const zones = useQuery({ queryKey: ['wms-zones'], queryFn: () => fetchAll<Zone>('/wms/zones/', { page_size: 500 }) })

  const zonesOf = (code: string) => (zones.data?.items ?? []).filter((z) => z.warehouse_code === code)
  const binCount = (code: string) => zonesOf(code).reduce((s, z) => s + (z.bin_count ?? 0), 0)
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['wms-warehouses'] })
    qc.invalidateQueries({ queryKey: ['wms-zones'] })
  }
  const delWh = useMutation({
    mutationFn: (id: string) => api.delete(`/wms/warehouses/${id}/`),
    onSuccess: () => { toast.success('Đã xoá kho'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })
  const delZone = useMutation({
    mutationFn: (id: string) => api.delete(`/wms/zones/${id}/`),
    onSuccess: () => { toast.success('Đã xoá khu'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <div className="max-w-4xl">
      <PageHeader icon={<WarehouseIcon size={20} className="text-flame" />} title="Kho & vị trí"
        subtitle={wh.data ? `${wh.data.count} kho` : undefined}
        actions={canControl && <Button onClick={() => setWhForm({ open: true, editing: null })}><Plus size={14} /> Thêm kho</Button>} />

      {wh.isLoading && <p className="text-txt-2 text-sm">Đang tải…</p>}
      {wh.isError && <p className="text-danger text-sm">Lỗi: {apiError(wh.error)}</p>}

      <div className="space-y-3">
        {wh.data?.items.map((w) => (
          <Card key={w.id}>
            <div className="flex items-start gap-2">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-mono text-flame font-semibold">{w.code}</span>
                  {w.is_default && <Tag tone="ok"><Star size={10} className="inline -mt-0.5" /> Mặc định</Tag>}
                  {!w.is_active && <Tag tone="gray">Ngừng</Tag>}
                </div>
                <div className="text-sm font-medium">{w.name}</div>
                {typeof w.address?.text === 'string' && w.address.text && (
                  <div className="text-xs text-txt-2 mt-0.5">{String(w.address.text)}</div>
                )}
                <div className="text-xs text-txt-2 mt-1">{zonesOf(w.code).length} khu · {binCount(w.code)} vị trí</div>
              </div>
              {canControl && (
                <div className="flex gap-1">
                  <Button variant="ghost" size="sm" onClick={() => setWhForm({ open: true, editing: w })}>
                    <Pencil size={13} /> Sửa
                  </Button>
                  <button title="Xoá kho"
                    onClick={() => { if (confirm(`Xoá kho ${w.code}?`)) delWh.mutate(w.id) }}
                    className="text-txt-2 hover:text-danger px-1"><Trash2 size={14} /></button>
                </div>
              )}
            </div>

            {/* Zones trong kho */}
            <div className="mt-3 pt-3 border-t border-line">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-txt-2 flex items-center gap-1.5"><Layers size={13} /> Khu (zone)</span>
                {canControl && (
                  <Button variant="ghost" size="sm" onClick={() => setZoneForm({ open: true, warehouse: w, editing: null })}>
                    <Plus size={12} /> Thêm khu
                  </Button>
                )}
              </div>
              {zonesOf(w.code).length === 0 && <p className="text-xs text-txt-2">Chưa có khu nào.</p>}
              <div className="grid sm:grid-cols-2 gap-1.5">
                {zonesOf(w.code).map((z) => (
                  <div key={z.id} className="flex items-center gap-2 border border-line rounded-md px-2.5 py-1.5 text-sm">
                    <span className="font-mono text-flame text-xs">{z.code}</span>
                    <span className="flex-1 truncate">{z.name}</span>
                    <span className="text-[11px] text-txt-2">{z.bin_count} ô</span>
                    {canControl && (
                      <div className="flex items-center gap-1.5 shrink-0">
                        <button title="Quản lý ô" onClick={() => setBinMgr({ warehouse: w, zone: z })}
                          className="text-txt-2 hover:text-flame"><Boxes size={13} /></button>
                        <button title="Sửa khu" onClick={() => setZoneForm({ open: true, warehouse: w, editing: z })}
                          className="text-txt-2 hover:text-flame"><Pencil size={12} /></button>
                        <button title="Xoá khu"
                          onClick={() => { if (confirm(`Xoá khu ${z.code} — ${z.name}?`)) delZone.mutate(z.id) }}
                          className="text-txt-2 hover:text-danger"><Trash2 size={12} /></button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </Card>
        ))}
      </div>

      {whForm.open && (
        <WarehouseForm editing={whForm.editing} onClose={() => setWhForm({ open: false, editing: null })} onSaved={invalidate} />
      )}
      {zoneForm.open && zoneForm.warehouse && (
        <ZoneForm warehouse={zoneForm.warehouse} editing={zoneForm.editing}
          onClose={() => setZoneForm({ open: false, editing: null })} onSaved={invalidate} />
      )}
      {binMgr && (
        <BinManager warehouse={binMgr.warehouse} zone={binMgr.zone}
          onClose={() => setBinMgr(null)} onChanged={invalidate} />
      )}
    </div>
  )
}

// ── Quản lý ô (bin) trong 1 khu ───────────────────────────────────────────
interface BinRow { id: string; rack: string; bin_code: string; full_code: string }

function BinManager({ warehouse, zone, onClose, onChanged }: {
  warehouse: Warehouse; zone: Zone; onClose: () => void; onChanged: () => void
}) {
  const qc = useQueryClient()
  const bins = useQuery({
    queryKey: ['wms-bins', zone.code],
    queryFn: () => fetchAll<BinRow>('/wms/bins/', { warehouse: warehouse.code, zone: zone.code, page_size: 2000 }),
  })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['wms-bins', zone.code] }); onChanged() }
  const { register, handleSubmit, reset, formState: { errors } } = useForm<{ rack: string; bin_code: string }>({
    defaultValues: { rack: '', bin_code: '' },
  })
  const add = useMutation({
    mutationFn: (d: { rack: string; bin_code: string }) => api.post('/wms/bins/', { zone: zone.id, ...d }),
    onSuccess: () => { toast.success('Đã thêm ô'); reset({ rack: '', bin_code: '' }); refresh() },
    onError: (e) => toast.error(apiError(e)),
  })
  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/wms/bins/${id}/`),
    onSuccess: () => { toast.success('Đã xoá ô'); refresh() },
    onError: (e) => toast.error(apiError(e)),
  })

  // Nhóm theo kệ → tầng
  const grouped: Record<string, Record<string, BinRow[]>> = {}
  for (const b of bins.data?.items ?? []) {
    const [ke, t = '-'] = b.rack.split('-T')
    ;((grouped[ke] ??= {})[t] ??= []).push(b)
  }

  return (
    <Modal open onClose={onClose} title={`Quản lý ô — ${warehouse.code}/${zone.code} (${zone.name})`}
      icon={<Boxes size={18} className="text-flame" />}
      footer={<Button variant="ghost" onClick={onClose}>Đóng</Button>}>
      <form onSubmit={handleSubmit((d) => add.mutate(d))} className="flex items-end gap-2 mb-3 pb-3 border-b border-line">
        <TextInput label="Kệ-Tầng *" placeholder="K06-T1" error={errors.rack?.message}
          {...register('rack', { required: 'Bắt buộc' })} />
        <TextInput label="Mã ô *" placeholder="09" error={errors.bin_code?.message}
          {...register('bin_code', { required: 'Bắt buộc' })} />
        <Button onClick={handleSubmit((d) => add.mutate(d))} disabled={add.isPending}><Plus size={14} /> Thêm ô</Button>
      </form>

      {bins.isLoading && <p className="text-txt-2 text-sm">Đang tải…</p>}
      <div className="max-h-[55vh] overflow-y-auto space-y-3">
        {Object.entries(grouped).map(([ke, tangs]) => (
          <div key={ke}>
            <div className="text-xs font-semibold text-txt-2 mb-1">Kệ {ke}</div>
            <div className="space-y-1">
              {Object.keys(tangs).sort((a, b) => b.localeCompare(a)).map((t) => (
                <div key={t} className="flex flex-wrap items-center gap-1">
                  {t !== '-' && <span className="text-[10px] text-txt-2 w-6">T{t}</span>}
                  {tangs[t].map((b) => (
                    <span key={b.id} title={b.full_code}
                      className="group inline-flex items-center gap-1 bg-ink-3 border border-line rounded px-1.5 py-0.5 text-[10px] font-mono">
                      {b.bin_code}
                      <button onClick={() => del.mutate(b.id)} className="text-txt-2 hover:text-danger">
                        <Trash2 size={10} />
                      </button>
                    </span>
                  ))}
                </div>
              ))}
            </div>
          </div>
        ))}
        {!bins.isLoading && (bins.data?.items.length ?? 0) === 0 && <p className="text-txt-2 text-sm">Khu chưa có ô nào.</p>}
      </div>
    </Modal>
  )
}

// ── Form Kho ──────────────────────────────────────────────────────────────
interface WhForm { code: string; name: string; address: string; is_default: boolean; is_active: boolean }

function WarehouseForm({ editing, onClose, onSaved }: { editing: Warehouse | null; onClose: () => void; onSaved: () => void }) {
  const { register, handleSubmit, reset, formState: { errors } } = useForm<WhForm>({
    defaultValues: { code: '', name: '', address: '', is_default: false, is_active: true },
  })
  useEffect(() => {
    reset(editing
      ? { code: editing.code, name: editing.name, address: String(editing.address?.text ?? ''), is_default: editing.is_default, is_active: editing.is_active }
      : { code: '', name: '', address: '', is_default: false, is_active: true })
  }, [editing, reset])

  const save = useMutation({
    mutationFn: (d: WhForm) => {
      const body = { code: d.code, name: d.name, address: { text: d.address }, is_default: d.is_default, is_active: d.is_active }
      return editing ? api.patch(`/wms/warehouses/${editing.id}/`, body) : api.post('/wms/warehouses/', body)
    },
    onSuccess: () => { toast.success(editing ? 'Đã cập nhật kho' : 'Đã tạo kho'); onSaved(); onClose() },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open onClose={onClose} title={editing ? `Sửa kho — ${editing.code}` : 'Thêm kho'}
      icon={<WarehouseIcon size={18} className="text-flame" />}
      footer={<><Button variant="ghost" onClick={onClose}>Hủy</Button>
        <Button onClick={handleSubmit((d) => save.mutate(d))} disabled={save.isPending}>{save.isPending ? 'Đang lưu…' : editing ? 'Lưu' : 'Tạo'}</Button></>}>
      <form onSubmit={handleSubmit((d) => save.mutate(d))}>
        <FieldRow>
          <TextInput label="Mã kho *" error={errors.code?.message} disabled={!!editing}
            {...register('code', { required: 'Bắt buộc' })} />
          <TextInput label="Tên kho *" error={errors.name?.message} {...register('name', { required: 'Bắt buộc' })} />
        </FieldRow>
        <TextInput label="Địa chỉ" full {...register('address')} />
        <div className="flex gap-5 mt-2 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" {...register('is_default')} /> Kho mặc định</label>
          <label className="flex items-center gap-2"><input type="checkbox" {...register('is_active')} /> Đang hoạt động</label>
        </div>
      </form>
    </Modal>
  )
}

// ── Form Khu (zone) ───────────────────────────────────────────────────────
interface ZForm { code: string; name: string; purpose: string }

function ZoneForm({ warehouse, editing, onClose, onSaved }: { warehouse: Warehouse; editing: Zone | null; onClose: () => void; onSaved: () => void }) {
  const { register, handleSubmit, reset, formState: { errors } } = useForm<ZForm>({ defaultValues: { code: '', name: '', purpose: '' } })
  useEffect(() => {
    reset(editing ? { code: editing.code, name: editing.name, purpose: editing.purpose } : { code: '', name: '', purpose: '' })
  }, [editing, reset])

  const save = useMutation({
    mutationFn: (d: ZForm) => {
      const body = { ...d, warehouse: warehouse.id }
      return editing ? api.patch(`/wms/zones/${editing.id}/`, body) : api.post('/wms/zones/', body)
    },
    onSuccess: () => { toast.success(editing ? 'Đã cập nhật khu' : 'Đã tạo khu'); onSaved(); onClose() },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open onClose={onClose} title={editing ? `Sửa khu — ${warehouse.code}/${editing.code}` : `Thêm khu — kho ${warehouse.code}`}
      icon={<Layers size={18} className="text-flame" />}
      footer={<><Button variant="ghost" onClick={onClose}>Hủy</Button>
        <Button onClick={handleSubmit((d) => save.mutate(d))} disabled={save.isPending}>{save.isPending ? 'Đang lưu…' : editing ? 'Lưu' : 'Tạo'}</Button></>}>
      <form onSubmit={handleSubmit((d) => save.mutate(d))}>
        <FieldRow>
          <TextInput label="Mã khu *" placeholder="A, B, C…" error={errors.code?.message} disabled={!!editing}
            {...register('code', { required: 'Bắt buộc' })} />
          <TextInput label="Tên khu *" error={errors.name?.message} {...register('name', { required: 'Bắt buộc' })} />
        </FieldRow>
        <TextInput label="Công năng (ghi chú)" full {...register('purpose')} />
      </form>
    </Modal>
  )
}
