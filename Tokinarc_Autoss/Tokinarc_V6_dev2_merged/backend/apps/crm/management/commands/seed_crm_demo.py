"""
Tokinarc V6 — apps/crm/management/commands/seed_crm_demo.py

Seed dữ liệu CRM mẫu (idempotent) để demo frontend: Customer + Contact + Lead +
Opportunity + Quote(+line) + Ticket + Visit + vài SalesOrder (cho Customer 360).

Chạy: python manage.py seed_crm_demo
Yêu cầu: đã chạy seed_users_roles trước (cần user sale1/quanly1/kysu1).
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.crm.models import (
    Activity, Contact, Contract, Customer, Lead, Opportunity, Quote, QuoteLine,
    Ticket, Visit,
)
from apps.sales.models import SalesOrder


class Command(BaseCommand):
    help = 'Seed dữ liệu CRM mẫu (idempotent).'

    @transaction.atomic
    def handle(self, *args, **opts):
        sale = User.objects.filter(username='sale1').first() or User.objects.filter(role='sales').first()
        mgr = User.objects.filter(username='quanly1').first()
        svc = User.objects.filter(username='kysu1').first() or sale
        if not sale:
            self.stderr.write('Chưa có user sale — chạy seed_users_roles trước.')
            return

        today = timezone.now().date()

        # ── Customers ────────────────────────────────────────────────────────
        cust_specs = [
            ('KH-0012', 'Dong Nai Steel',        'factory',    'vip',       'Đồng Nai'),
            ('KH-0003', 'Hanoi Robot Welding',   'integrator', 'potential', 'Hà Nội'),
            ('KH-0008', 'Vina Steel Corp',       'factory',    'new',       'HCM'),
            ('KH-0021', 'Saigon Metalwork',      'dealer',     'normal',    'HCM'),
            ('KH-0030', 'Vung Tau Offshore',     'shipyard',   'potential', 'Vũng Tàu'),
        ]
        cust = {}
        for code, name, seg, status, region in cust_specs:
            obj, _ = Customer.objects.get_or_create(
                code=code,
                defaults=dict(name=name, segment=seg, status=status, region=region, owner=sale),
            )
            cust[code] = obj

        # ── Contacts (cho Dong Nai Steel) ────────────────────────────────────
        dns = cust['KH-0012']
        contact_specs = [
            ('Ông Hùng', 'GĐ Nhà máy',   '0901234567', 'hung@dnsteel.vn',  'zalo',  True),
            ('Bà Bình',  'Trưởng mua hàng','0901234568', 'binh@dnsteel.vn', 'email', False),
            ('Anh Toàn', 'Kỹ sư hàn',     '0901234569', 'toan@dnsteel.vn',  'phone', False),
        ]
        for full_name, title, phone, email, channel, primary in contact_specs:
            Contact.objects.get_or_create(
                customer=dns, full_name=full_name,
                defaults=dict(title=title, phone=phone, email=email,
                              preferred_channel=channel, is_primary=primary),
            )

        # ── Leads ────────────────────────────────────────────────────────────
        lead_specs = [
            ('Binh Duong Auto', 'Binh Duong Auto Co.', '0911222333', 'zalo',     85, 'new'),
            ('Can Tho Fab',     'Can Tho Fabrication', '0922333444', 'web',      60, 'new'),
            ('Long An Steel',   'Long An Steel JSC',   '0933444555', 'referral', 90, 'contacted'),
        ]
        for name, company, phone, source, score, status in lead_specs:
            Lead.objects.get_or_create(
                name=name, owner=sale,
                defaults=dict(company=company, phone=phone, source=source, score=score, status=status),
            )

        # ── Opportunities ────────────────────────────────────────────────────
        opp_specs = [
            ('KH-0003', 'HRW - Dây chuyền robot', 'negotiate', 780_000_000, 80, today + timedelta(days=42)),
            ('KH-0008', 'Vina - Nâng cấp WX',     'proposal',  320_000_000, 60, today + timedelta(days=27)),
            ('KH-0012', 'DNS - Bổ sung torch',    'negotiate', 185_000_000, 90, today + timedelta(days=17)),
            ('KH-0021', 'Saigon - Mở rộng đại lý','qualify',   120_000_000, 40, today + timedelta(days=50)),
            ('KH-0030', 'Vung Tau - TIG offshore','prospect',  145_000_000, 20, today + timedelta(days=63)),
        ]
        for ccode, title, stage, val, prob, close in opp_specs:
            Opportunity.objects.get_or_create(
                customer=cust[ccode], title=title, owner=sale,
                defaults=dict(stage=stage, est_value_vnd=val, probability=prob, expected_close=close),
            )

        # ── Quotes (+ lines) ─────────────────────────────────────────────────
        quote_specs = [
            ('BG-0001', 'KH-0012', 'sent',     None, [('YMSA-500R', 'YMSA-500R Robotic Torch', 2, 92_500_000)]),
            ('BG-0002', 'KH-0003', 'approved', mgr,  [('TK-508RR', 'TK-508RR Torch', 5, 156_000_000)]),
            ('BG-0003', 'KH-0008', 'draft',    None, [('WX-500R', 'WX-500R Torch', 3, 106_666_667)]),
        ]
        for code, ccode, status, approver, lines in quote_specs:
            q, created = Quote.objects.get_or_create(
                code=code,
                defaults=dict(customer=cust[ccode], owner=sale, status=status,
                              approved_by=approver, due_date=today + timedelta(days=20)),
            )
            if created:
                for part_no, part_name, qty, price in lines:
                    QuoteLine.objects.create(quote=q, part_no=part_no, part_name=part_name,
                                             qty=qty, unit_price_vnd=price)
                q.recompute_total()
                q.save(update_fields=['total_vnd'])

        # ── Tickets ──────────────────────────────────────────────────────────
        ticket_specs = [
            ('TK-0451', 'KH-0012', 'Torch lỗi cấp khí',        'high',   'in_progress'),
            ('TK-0450', 'KH-0008', 'Wire feed kẹt',            'medium', 'open'),
            ('TK-0449', 'KH-0003', 'Robot báo lỗi sensor',     'high',   'open'),
        ]
        for code, ccode, title, prio, status in ticket_specs:
            Ticket.objects.get_or_create(
                code=code,
                defaults=dict(customer=cust[ccode], title=title, priority=prio,
                              status=status, created_owner=svc, assignee=svc),
            )

        # ── Visits ───────────────────────────────────────────────────────────
        visit_specs = [
            ('KH-0012', today,                  'Demo YMSA-500R', 'Chốt đơn tuần sau', {'lat': 10.94, 'lng': 106.82}),
            ('KH-0008', today - timedelta(1),   'Khảo sát dây chuyền', 'Gửi báo giá', {'lat': 10.76, 'lng': 106.66}),
        ]
        for ccode, vdate, purpose, next_action, gps in visit_specs:
            Visit.objects.get_or_create(
                customer=cust[ccode], visit_date=vdate, purpose=purpose,
                defaults=dict(next_action=next_action, gps=gps, owner=sale),
            )

        # ── SalesOrders (cho Customer 360: đơn mở + công nợ) ──────────────────
        order_specs = [
            ('HD-2026-001', 'KH-0012', 185_000_000,  93_000_000, 'active'),
            ('HD-2026-002', 'KH-0003', 780_000_000, 780_000_000, 'completed'),
            ('HD-2026-003', 'KH-0008', 320_000_000,           0, 'pending'),
        ]
        for code, ccode, total, paid, status in order_specs:
            SalesOrder.objects.get_or_create(
                code=code,
                defaults=dict(customer=cust[ccode], owner=sale, issued_date=today,
                              total_vnd=total, paid_vnd=paid, status=status),
            )

        # ── Contracts (Hợp đồng) ─────────────────────────────────────────────
        contract_specs = [
            ('HD-0021', 'KH-0012', 'HĐ cung cấp torch YMSA', 185_000_000, 93_000_000, 'active',
             today - timedelta(20), today + timedelta(160)),
            ('HD-0020', 'KH-0003', 'HĐ dây chuyền robot',    780_000_000, 780_000_000, 'active',
             today - timedelta(40), today + timedelta(320)),
            ('HD-0019', 'KH-0008', 'HĐ nâng cấp WX',         320_000_000,          0, 'pending_sign',
             None, None),
            ('HD-0015', 'KH-0021', 'HĐ phụ tùng năm',        145_000_000,  120_000_000, 'expired',
             today - timedelta(400), today - timedelta(20)),
        ]
        for code, ccode, title, val, paid, status, sd, ed in contract_specs:
            Contract.objects.get_or_create(
                code=code,
                defaults=dict(customer=cust[ccode], owner=sale, title=title,
                              value_vnd=val, paid_vnd=paid, status=status,
                              start_date=sd, end_date=ed),
            )

        # ── Activities (Hoạt động) ───────────────────────────────────────────
        from django.utils import timezone as _tz
        act_specs = [
            ('KH-0012', 'call',    'Trao đổi đơn YMSA-500R x2, KH đồng ý giá'),
            ('KH-0003', 'email',   'Gửi báo giá TK-508RR x5'),
            ('KH-0008', 'meeting', 'Demo WX-500R tại nhà máy'),
            ('KH-0012', 'zalo',    'Nhắc lịch giao hàng tuần sau'),
        ]
        if Activity.objects.count() == 0:
            for ccode, atype, content in act_specs:
                Activity.objects.create(customer=cust[ccode], activity_type=atype,
                                        content=content, owner=sale, activity_date=_tz.now())

        self.stdout.write(self.style.SUCCESS(
            f'✅ Seed CRM: {Customer.objects.count()} KH, {Lead.objects.count()} lead, '
            f'{Opportunity.objects.count()} opp, {Quote.objects.count()} báo giá, '
            f'{Ticket.objects.count()} ticket, {Visit.objects.count()} visit, '
            f'{SalesOrder.objects.count()} đơn hàng, {Contract.objects.count()} HĐ, '
            f'{Activity.objects.count()} hoạt động.'
        ))
