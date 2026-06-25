"""
Tokinarc V6.C — apps/crm/lead_intake.py

Cổng GHI-1-CHIỀU cho BOT KHÁCH (FastAPI) đẩy lead về CRM.

Nguyên tắc tách 2 bot vẫn giữ:
  - Endpoint NÀY chỉ TẠO Lead (source=chatbot_khach). KHÔNG đọc dữ liệu nội bộ.
  - Xác thực bằng khóa riêng X-Intake-Key (settings.LEAD_INTAKE_KEY), KHÔNG dùng
    JWT người dùng (khách ẩn danh). Bot khách không có quyền gì khác ngoài tạo lead.
"""
from __future__ import annotations

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.common.models import notify

from .models import Lead, LeadStatus


def _default_owner() -> User | None:
    """Chủ lead mặc định: cấu hình LEAD_INTAKE_OWNER → sale đầu tiên → admin."""
    uname = getattr(settings, 'LEAD_INTAKE_OWNER', '') or ''
    if uname:
        u = User.objects.filter(username=uname).first()
        if u:
            return u
    return (User.objects.filter(role=Role.SALES).order_by('id').first()
            or User.objects.filter(role=Role.ADMIN).order_by('id').first()
            or User.objects.order_by('id').first())


class LeadIntakeView(APIView):
    """POST /api/v1/crm/lead-intake/ — bot khách tạo lead. Header: X-Intake-Key."""
    permission_classes = [AllowAny]
    authentication_classes = []   # không cần JWT; chỉ kiểm tra intake key

    def post(self, request):
        key = request.headers.get('X-Intake-Key', '')
        expected = getattr(settings, 'LEAD_INTAKE_KEY', '') or ''
        if not expected or key != expected:
            return Response({'detail': 'Sai hoặc thiếu intake key.'},
                            status=status.HTTP_401_UNAUTHORIZED)

        data = request.data or {}
        name = (data.get('name') or '').strip()
        phone = (data.get('phone') or '').strip()
        if not name and not phone:
            return Response({'detail': 'Cần ít nhất tên hoặc số điện thoại.'},
                            status=status.HTTP_400_BAD_REQUEST)

        owner = _default_owner()
        if owner is None:
            return Response({'detail': 'Hệ thống chưa có người nhận lead.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        lead = Lead.objects.create(
            name=name or f'Khách {phone}',
            company=(data.get('company') or '').strip(),
            phone=phone,
            email=(data.get('email') or '').strip(),
            source='chatbot_khach',
            status=LeadStatus.NEW,
            notes=(data.get('note') or data.get('need') or '').strip(),
            owner=owner,
        )
        # Báo sale chủ lead: có khách mới từ chatbot — gọi ngay.
        notify(owner, 'lead_new',
               f"Lead mới từ chatbot: {lead.name}"
               + (f" ({lead.phone})" if lead.phone else '') + ' — gọi khách.',
               link='/leads')
        return Response({'ok': True, 'id': str(lead.id), 'name': lead.name},
                        status=status.HTTP_201_CREATED)
