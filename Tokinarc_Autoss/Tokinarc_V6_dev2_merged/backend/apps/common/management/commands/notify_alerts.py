"""
Tokinarc — apps/common/management/commands/notify_alerts.py

Cảnh báo định kỳ (chạy hằng ngày qua cron/scheduler):
    python manage.py notify_alerts

  - Lô hàng sắp hết hạn (FEFO)  → báo nhân viên kho.
  - Công nợ KH quá hạn          → báo sale phụ trách KH.

Dùng "mốc ngày" (milestone) để KHÔNG spam: mỗi lô/đơn chỉ bắn noti khi số ngày
còn lại / quá hạn rơi đúng mốc — chạy hằng ngày thì mỗi mốc bắn tối đa 1 lần.
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import F

from apps.accounts.roles import MANAGER_ROLES, Role
from apps.common.models import notify, notify_roles

WAREHOUSE_STAFF = frozenset({Role.WAREHOUSE, Role.WAREHOUSE_MANAGER})
PURCHASING_STAFF = frozenset({Role.WAREHOUSE_MANAGER}) | MANAGER_ROLES   # mua hàng + quản lý
LOT_MILESTONES = {30, 7, 1}            # ngày trước khi hết hạn
DEBT_MILESTONES = {1, 15, 30, 60}      # ngày sau khi quá hạn
PO_OVERDUE_MILESTONES = {1, 3, 7, 14}  # ngày hàng mua về TRỄ so với dự kiến


class Command(BaseCommand):
    help = "Bắn noti cảnh báo: lô sắp hết hạn (kho) + công nợ quá hạn (sale)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Chỉ in, không gửi noti.')

    def handle(self, *args, dry_run=False, **kw):
        today = date.today()
        n_lot = self._lots(today, dry_run)
        n_debt = self._debts(today, dry_run)
        n_po = self._po_overdue(today, dry_run)
        tag = '[dry-run] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f"{tag}Lô sắp hết hạn: {n_lot} noti · Công nợ quá hạn: {n_debt} noti · "
            f"Hàng mua về trễ: {n_po} noti."))

    def _po_overdue(self, today, dry_run) -> int:
        """Đơn mua đã đặt/nhận một phần mà quá ngày dự kiến về → báo mua hàng + quản lý."""
        from apps.purchasing.models import PurchaseOrder
        sent = 0
        qs = (PurchaseOrder.objects
              .filter(status__in=['ordered', 'partial'], expected_date__lt=today)
              .select_related('supplier'))
        for po in qs:
            late = (today - po.expected_date).days
            if late not in PO_OVERDUE_MILESTONES:
                continue
            msg = (f"Hàng về TRỄ {late} ngày: đơn mua {po.code} ({po.supplier.name}) "
                   f"dự kiến {po.expected_date} chưa nhận đủ — giục nhà cung cấp.")
            if dry_run:
                self.stdout.write(f"  [po] {msg}")
            else:
                sent += notify_roles(PURCHASING_STAFF, 'po_overdue', msg, link='/purchasing/orders')
        return sent

    def _lots(self, today, dry_run) -> int:
        from apps.wms.models import Lot
        sent = 0
        qs = Lot.objects.filter(qty_remaining__gt=0, expires_at__isnull=False).select_related('part')
        for lot in qs:
            days = (lot.expires_at - today).days
            if days not in LOT_MILESTONES:
                continue
            msg = (f"Lô {lot.lot_no} ({lot.part_id}) còn {lot.qty_remaining} "
                   f"sắp hết hạn sau {days} ngày ({lot.expires_at}).")
            if dry_run:
                self.stdout.write(f"  [lot] {msg}")
            else:
                sent += notify_roles(WAREHOUSE_STAFF, 'lot_expiring', msg, link='/wms/lots')
        return sent

    def _debts(self, today, dry_run) -> int:
        from apps.crm.receivables import _due_date
        from apps.sales.models import SalesOrder
        sent = 0
        qs = (SalesOrder.objects
              .filter(status__in=['active', 'shipping', 'completed'], total_vnd__gt=F('paid_vnd'))
              .select_related('customer', 'customer__owner'))
        for o in qs:
            overdue = (today - _due_date(o)).days
            if overdue not in DEBT_MILESTONES:
                continue
            owner = getattr(o.customer, 'owner', None)
            amount = int(o.total_vnd - o.paid_vnd)
            msg = (f"Công nợ quá hạn {overdue} ngày: đơn {o.code} ({o.customer.name}) "
                   f"còn {amount:,} đ — nhắc khách thanh toán.".replace(',', '.'))
            if dry_run:
                self.stdout.write(f"  [debt] {msg}")
            elif owner is not None:
                notify(owner, 'debt_overdue', msg, link='/receivables')
                sent += 1
        return sent
