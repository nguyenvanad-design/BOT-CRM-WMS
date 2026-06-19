/**
 * Tokinarc frontend — src/lib/wms.ts
 * Nhãn + tone tag cho enum WMS (khớp apps/wms/models.py).
 */
import type {
  SerialStatus, MovementReason, InboundStatus, OutboundStatus, OutboundRule,
} from '@/lib/types'
import type { TagTone } from '@/lib/crm'

export const SERIAL_STATUS_LABEL: Record<SerialStatus, string> = {
  in_stock: 'Trong kho', reserved: 'Đã giữ', shipped: 'Đã giao',
  sold: 'Đã bán', returned: 'Trả lại', scrapped: 'Hủy',
}
export const SERIAL_STATUS_TONE: Record<SerialStatus, TagTone> = {
  in_stock: 'ok', reserved: 'warn', shipped: 'blue',
  sold: 'purple', returned: 'gray', scrapped: 'danger',
}

export const MOVE_REASON_LABEL: Record<MovementReason, string> = {
  inbound: 'Nhập kho', outbound: 'Xuất kho', adjust: 'Điều chỉnh',
  transfer: 'Chuyển kho', return: 'Trả hàng',
}
export const MOVE_REASON_TONE: Record<MovementReason, TagTone> = {
  inbound: 'ok', outbound: 'danger', adjust: 'warn', transfer: 'blue', return: 'purple',
}

export const INBOUND_STATUS_LABEL: Record<InboundStatus, string> = {
  draft: 'Nháp', confirmed: 'Đã xác nhận', putaway: 'Đã cất kho', cancelled: 'Hủy',
}
export const INBOUND_STATUS_TONE: Record<InboundStatus, TagTone> = {
  draft: 'gray', confirmed: 'blue', putaway: 'ok', cancelled: 'danger',
}

export const OUTBOUND_STATUS_LABEL: Record<OutboundStatus, string> = {
  draft: 'Nháp', picking: 'Đang soạn', picked: 'Đã soạn xong', shipped: 'Đã giao', cancelled: 'Hủy',
}
export const OUTBOUND_STATUS_TONE: Record<OutboundStatus, TagTone> = {
  draft: 'gray', picking: 'warn', picked: 'blue', shipped: 'ok', cancelled: 'danger',
}

export const RULE_LABEL: Record<OutboundRule, string> = {
  FIFO: 'FIFO (nhập trước xuất trước)', FEFO: 'FEFO (hết hạn trước)', NEAREST: 'Gần nhất',
}
