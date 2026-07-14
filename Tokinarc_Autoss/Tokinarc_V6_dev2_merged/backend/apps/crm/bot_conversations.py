"""
Tokinarc V6 — apps/crm/bot_conversations.py

LƯU & QUẢN LÝ HỘI THOẠI BOT KHÁCH cho nhân viên (sale/quản lý) xem và tiếp quản.

Kiến trúc (giữ nguyên tắc tách 2 bot):
  - Bot khách (FastAPI) ĐẨY từng lượt hội thoại về đây bằng khóa X-Intake-Key
    (dùng chung LEAD_INTAKE_KEY) — GHI 1 CHIỀU, KHÔNG cho bot đọc dữ liệu nội bộ.
  - Nhân viên nội bộ ĐỌC/QUẢN LÝ qua JWT + role: xem thread, nhận (assign), gắn cờ
    (khách nóng), đóng, và ghi CHÚ THÍCH NỘI BỘ (tiếp quản mềm).

Model:
  BotConversation  — 1 phiên chat (session_key từ bot), gắn Lead nếu bắt được liên hệ.
  BotMessage       — từng tin nhắn (user / bot / agent-nhân viên).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models, transaction
from django.db.models import Q
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.roles import INTERNAL_ROLES, Role, is_manager, role_of
from apps.common.models import BaseModel, notify

from .models import Lead


# ─── Models ──────────────────────────────────────────────────────────────────
class ConvStatus(models.TextChoices):
    OPEN        = 'open',         'Đang mở'
    NEEDS_HUMAN = 'needs_human',  'Cần người'
    CLOSED      = 'closed',       'Đã đóng'


class MsgRole(models.TextChoices):
    USER  = 'user',  'Khách'
    BOT   = 'bot',   'Bot'
    AGENT = 'agent', 'Nhân viên'


class BotConversation(BaseModel):
    """1 phiên hội thoại giữa BOT KHÁCH và 1 khách (ẩn danh cho tới khi để lại liên hệ)."""
    session_key    = models.CharField(max_length=64, unique=True, db_index=True)
    channel        = models.CharField(max_length=20, default='web', db_index=True)  # web/zalo/...
    customer_name  = models.CharField(max_length=200, blank=True)
    customer_phone = models.CharField(max_length=20, blank=True, db_index=True)
    lead           = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='bot_conversations')
    owner          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='bot_conversations')
    status         = models.CharField(max_length=16, choices=ConvStatus.choices,
                                      default=ConvStatus.OPEN, db_index=True)
    flagged        = models.BooleanField(default=False, db_index=True)  # khách "nóng"
    message_count  = models.IntegerField(default=0)
    unread         = models.IntegerField(default=0)   # tin khách CHƯA đọc; reset khi staff mở
    last_message_at = models.DateTimeField(db_index=True, null=True, blank=True)

    class Meta:
        db_table = 'crm_bot_conversation'
        ordering = ['-last_message_at', '-created_at']
        indexes = [models.Index(fields=['status', '-last_message_at'], name='crm_botconv_status_idx')]

    def __str__(self) -> str:
        return f"{self.session_key[:8]} · {self.customer_name or 'ẩn danh'}"


class BotMessage(models.Model):
    id           = models.BigAutoField(primary_key=True)
    conversation = models.ForeignKey(BotConversation, on_delete=models.CASCADE, related_name='messages')
    role         = models.CharField(max_length=8, choices=MsgRole.choices)
    text         = models.TextField()
    intent       = models.CharField(max_length=60, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'crm_bot_message'
        ordering = ['created_at', 'id']

    def __str__(self) -> str:
        return f"[{self.role}] {self.text[:40]}"


# ─── Serializers ─────────────────────────────────────────────────────────────
class BotMessageSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = BotMessage
        fields = ['id', 'role', 'role_display', 'text', 'intent', 'created_at']


class BotConversationListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    channel_display = serializers.SerializerMethodField()
    owner_username = serializers.CharField(source='owner.username', read_only=True, default=None)
    last_preview   = serializers.SerializerMethodField()

    class Meta:
        model = BotConversation
        fields = ['id', 'session_key', 'channel', 'channel_display', 'customer_name',
                  'customer_phone', 'lead', 'owner', 'owner_username', 'status', 'status_display',
                  'flagged', 'message_count', 'unread', 'last_message_at', 'last_preview', 'created_at']

    def get_channel_display(self, obj) -> str:
        return {'web': 'Website', 'zalo': 'Zalo', 'facebook': 'Facebook',
                'whatsapp': 'WhatsApp'}.get(obj.channel, obj.channel or 'Website')

    def get_last_preview(self, obj) -> str:
        m = obj.messages.order_by('-created_at', '-id').first()
        return (m.text[:120] if m else '')


class BotConversationDetailSerializer(BotConversationListSerializer):
    messages = BotMessageSerializer(many=True, read_only=True)

    class Meta(BotConversationListSerializer.Meta):
        fields = BotConversationListSerializer.Meta.fields + ['messages']


# ─── Ingest (bot khách đẩy từng lượt về — keyed) ─────────────────────────────
class BotConversationIngestView(APIView):
    """POST /api/v1/crm/bot-conversations/ingest/ — bot khách ghi 1 lượt hội thoại.
    Header: X-Intake-Key (dùng chung LEAD_INTAKE_KEY). Body: session_key, user_text,
    bot_text, [channel, intent, customer_name, customer_phone]."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        key = request.headers.get('X-Intake-Key', '')
        expected = getattr(settings, 'LEAD_INTAKE_KEY', '') or ''
        if not expected or key != expected:
            return Response({'detail': 'Sai hoặc thiếu intake key.'}, status=status.HTTP_401_UNAUTHORIZED)

        data = request.data or {}
        session_key = (data.get('session_key') or '').strip()
        if not session_key:
            return Response({'detail': 'Thiếu session_key.'}, status=status.HTTP_400_BAD_REQUEST)
        user_text = (data.get('user_text') or '').strip()
        bot_text  = (data.get('bot_text') or '').strip()
        if not user_text and not bot_text:
            return Response({'detail': 'Không có nội dung tin nhắn.'}, status=status.HTTP_400_BAD_REQUEST)

        from django.utils import timezone
        with transaction.atomic():
            conv, _ = BotConversation.objects.select_for_update().get_or_create(
                session_key=session_key,
                defaults={'channel': (data.get('channel') or 'web').strip() or 'web'})

            # Cập nhật thông tin khách nếu bot gửi kèm (khách vừa để lại liên hệ).
            name = (data.get('customer_name') or '').strip()
            phone = (data.get('customer_phone') or '').strip()
            dirty = []
            if name and not conv.customer_name:
                conv.customer_name = name[:200]; dirty.append('customer_name')
            if phone and not conv.customer_phone:
                conv.customer_phone = phone[:20]; dirty.append('customer_phone')
            # Gắn Lead nếu match theo SĐT (bot khách thường tạo lead qua lead-intake).
            if conv.lead_id is None and (phone or conv.customer_phone):
                lead = Lead.objects.filter(phone=phone or conv.customer_phone).order_by('-created_at').first()
                if lead:
                    conv.lead = lead; dirty.append('lead')

            intent = (data.get('intent') or '').strip()[:60]
            msgs = []
            if user_text:
                msgs.append(BotMessage(conversation=conv, role=MsgRole.USER, text=user_text, intent=intent))
            if bot_text:
                msgs.append(BotMessage(conversation=conv, role=MsgRole.BOT, text=bot_text, intent=intent))
            BotMessage.objects.bulk_create(msgs)

            conv.message_count = (conv.message_count or 0) + len(msgs)
            if user_text:                       # có tin của KHÁCH → +1 chưa đọc
                conv.unread = (conv.unread or 0) + 1
            conv.last_message_at = timezone.now()
            conv.save(update_fields=dirty + ['message_count', 'unread', 'last_message_at', 'updated_at'])

        return Response({'ok': True, 'id': str(conv.id), 'messages': len(msgs)},
                        status=status.HTTP_201_CREATED)


# ─── Staff API (JWT + role) ──────────────────────────────────────────────────
class IsInternalStaff(BasePermission):
    """Chỉ nhân viên nội bộ (role != customer). Khách KHÔNG bao giờ xem được hội thoại."""
    message = "Chỉ nhân viên nội bộ xem được hội thoại bot."

    def has_permission(self, request, view) -> bool:
        u = request.user
        return bool(u and u.is_authenticated and role_of(u) in INTERNAL_ROLES)


_WRITE_ROLES = frozenset({Role.SALES, Role.MANAGER, Role.CEO})


class BotConversationViewSet(viewsets.ReadOnlyModelViewSet):
    """Xem & quản lý hội thoại bot khách. Sale thấy hội thoại CHƯA có chủ + của mình;
    quản lý/CEO/admin thấy tất cả. Hành động: nhận / gắn cờ / đóng / ghi chú nội bộ."""
    permission_classes = [IsInternalStaff]

    def get_serializer_class(self):
        return BotConversationDetailSerializer if self.action == 'retrieve' else BotConversationListSerializer

    def retrieve(self, request, *args, **kwargs):
        """Mở 1 hội thoại → đánh dấu đã đọc (reset unread)."""
        resp = super().retrieve(request, *args, **kwargs)
        obj = self.get_object()
        if obj.unread:
            BotConversation.objects.filter(pk=obj.pk).update(unread=0)
            resp.data['unread'] = 0
        return resp

    def get_queryset(self):
        qs = BotConversation.objects.select_related('owner', 'lead').prefetch_related('messages')
        u = self.request.user
        if not is_manager(u) and role_of(u) != Role.ADMIN:
            qs = qs.filter(Q(owner=u) | Q(owner__isnull=True))   # sale: chưa có chủ + của mình
        # Bộ lọc nhanh cho FE.
        p = self.request.query_params
        if p.get('status'):
            qs = qs.filter(status=p['status'])
        if p.get('channel'):
            qs = qs.filter(channel=p['channel'])
        if p.get('flagged') == 'true':
            qs = qs.filter(flagged=True)
        if p.get('has_lead') == 'true':
            qs = qs.filter(lead__isnull=False)
        return qs

    def _check_write(self, request):
        if role_of(request.user) not in _WRITE_ROLES:
            return Response({'detail': 'Bạn không có quyền thao tác hội thoại.'}, status=403)
        return None

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        """Nhận hội thoại về mình, hoặc quản lý giao cho sale khác (?owner=<id>)."""
        if (err := self._check_write(request)):
            return err
        conv = self.get_object()
        target = request.user
        owner_id = request.data.get('owner')
        if owner_id:
            if not is_manager(request.user):
                return Response({'detail': 'Chỉ quản lý được giao cho người khác.'}, status=403)
            target = User.objects.filter(pk=owner_id, is_active=True).first()
            if target is None:
                return Response({'detail': 'Người nhận không hợp lệ.'}, status=400)
        conv.owner = target
        conv.save(update_fields=['owner', 'updated_at'])
        if target.id != request.user.id:
            notify(target, 'bot_conv_assigned',
                   f"Bạn được giao hội thoại bot: {conv.customer_name or 'khách ẩn danh'}"
                   + (f" ({conv.customer_phone})" if conv.customer_phone else ''),
                   link='/bot-conversations')
        return Response(BotConversationListSerializer(conv).data)

    @action(detail=True, methods=['post'])
    def flag(self, request, pk=None):
        """Bật/tắt cờ 'khách nóng'."""
        if (err := self._check_write(request)):
            return err
        conv = self.get_object()
        conv.flagged = not conv.flagged
        conv.save(update_fields=['flagged', 'updated_at'])
        return Response({'flagged': conv.flagged})

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """Đóng hội thoại (đã xử lý xong)."""
        if (err := self._check_write(request)):
            return err
        conv = self.get_object()
        conv.status = ConvStatus.CLOSED
        conv.save(update_fields=['status', 'updated_at'])
        return Response({'status': conv.status})

    @action(detail=True, methods=['post'])
    def note(self, request, pk=None):
        """Ghi chú nội bộ vào thread (role=agent) — tiếp quản mềm."""
        if (err := self._check_write(request)):
            return err
        text = (request.data.get('text') or '').strip()
        if not text:
            return Response({'detail': 'Ghi chú trống.'}, status=400)
        conv = self.get_object()
        from django.utils import timezone
        BotMessage.objects.create(conversation=conv, role=MsgRole.AGENT,
                                  text=f"[{request.user.username}] {text}")
        conv.message_count = (conv.message_count or 0) + 1
        conv.last_message_at = timezone.now()
        conv.save(update_fields=['message_count', 'last_message_at', 'updated_at'])
        return Response(BotConversationDetailSerializer(conv).data)

    @action(detail=True, methods=['post'])
    def takeover(self, request, pk=None):
        """Tiếp quản từ bot: nhận về mình + đánh dấu CẦN NGƯỜI xử lý (bot ngừng tự chạy)."""
        if (err := self._check_write(request)):
            return err
        conv = self.get_object()
        conv.owner = request.user
        conv.status = ConvStatus.NEEDS_HUMAN
        conv.save(update_fields=['owner', 'status', 'updated_at'])
        return Response(BotConversationDetailSerializer(conv).data)

    @action(detail=True, methods=['post'])
    def reply(self, request, pk=None):
        """Nhân viên TRẢ LỜI khách (role=agent). Tự nhận hội thoại nếu chưa có chủ.
        Lưu ý: gửi thật tới khách cần webhook Zalo/FB; hiện ghi vào thread cho nhân sự."""
        if (err := self._check_write(request)):
            return err
        text = (request.data.get('text') or '').strip()
        if not text:
            return Response({'detail': 'Nội dung trả lời trống.'}, status=400)
        conv = self.get_object()
        from django.utils import timezone
        BotMessage.objects.create(conversation=conv, role=MsgRole.AGENT, text=text,
                                  intent=f"reply:{request.user.username}")
        fields = ['message_count', 'last_message_at', 'updated_at']
        conv.message_count = (conv.message_count or 0) + 1
        conv.last_message_at = timezone.now()
        if conv.owner_id is None:                       # trả lời = tiếp quản
            conv.owner = request.user
            conv.status = ConvStatus.NEEDS_HUMAN
            fields += ['owner', 'status']
        conv.save(update_fields=fields)
        return Response(BotConversationDetailSerializer(conv).data)
