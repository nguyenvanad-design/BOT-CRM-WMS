/**
 * Tokinarc frontend — src/pages/wms/Trace.tsx
 * Truy xuất nguồn gốc: gộp Serial (theo cái) + Lô hàng (theo lô) qua toggle.
 */
import { useState } from 'react'
import { Barcode, Boxes } from 'lucide-react'
import { PageHeader } from '@/components/ui'
import { SerialsList } from '@/pages/wms/Serials'
import { LotsList } from '@/pages/wms/Lots'

export function TracePage() {
  const [view, setView] = useState<'serial' | 'lot'>('serial')
  return (
    <div className="max-w-5xl">
      <PageHeader
        icon={<Barcode size={20} className="text-flame" />}
        title="Truy xuất"
        subtitle={view === 'serial' ? 'Theo từng cái (serial) — bảo hành, đã bán' : 'Theo lô — hạn dùng, FEFO'}
        actions={
          <div className="flex rounded-md border border-line overflow-hidden">
            <button onClick={() => setView('serial')}
              className={`flex items-center gap-1 text-xs px-2.5 py-1.5 ${view === 'serial' ? 'bg-flame/15 text-flame' : 'text-txt-2 hover:text-txt'}`}>
              <Barcode size={13} /> Serial
            </button>
            <button onClick={() => setView('lot')}
              className={`flex items-center gap-1 text-xs px-2.5 py-1.5 ${view === 'lot' ? 'bg-flame/15 text-flame' : 'text-txt-2 hover:text-txt'}`}>
              <Boxes size={13} /> Lô hàng
            </button>
          </div>
        }
      />
      {view === 'serial' ? <SerialsList /> : <LotsList />}
    </div>
  )
}
