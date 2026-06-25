"""
Tokinarc V6.C — apps/accounts/views.py

Auth flow khớp V6.B.3 §2:
  POST /api/v1/auth/login/      → {access, refresh, user}  (+ lockout)
  POST /api/v1/auth/refresh/    → {access, refresh}
  GET  /api/v1/auth/me/         → user
  POST /api/v1/auth/logout/     → 204 (blacklist refresh)
  GET  /.well-known/jwks.json   → public key cho FastAPI sidecar verify

User management (admin):
  /api/v1/accounts/users/  + POST {id}/set-role/

JWKS: nếu cấu hình RS256 (SIMPLE_JWT['VERIFYING_KEY']) thì xuất JWK từ public key.
Khi dev dùng HS256 (mặc định simplejwt) thì JWKS trả keys rỗng — sidecar verify
bằng shared secret. Production B.5 §4.2 dùng RS256.
"""
from __future__ import annotations

from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.roles import Role, role_of
from apps.common.models import AuditLog

from . import services
from .models import User
from .serializers import (
    LoginSerializer, SetRoleSerializer, UserSerializer, UserWriteSerializer,
)


def _ip(request) -> str:
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')


def _tokens_for(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    refresh['role'] = user.role
    refresh['customer_id'] = str(user.customer_id) if user.customer_id else None
    access = refresh.access_token
    access['role'] = user.role
    access['customer_id'] = str(user.customer_id) if user.customer_id else None
    return {'access': str(access), 'refresh': str(refresh)}


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        username = ser.validated_data['username']
        password = ser.validated_data['password']
        ip = _ip(request)

        if services.is_locked(username, ip):
            return Response(
                {'detail': 'Tài khoản tạm khóa, thử lại sau 15 phút.', 'code': 'RATE_LIMITED'},
                status=status.HTTP_429_TOO_MANY_REQUESTS)

        try:
            user = User.objects.get(username=username, is_active=True)
        except User.DoesNotExist:
            user = None

        if user is None or not user.check_password(password):
            n = services.record_fail(username, ip)
            return Response(
                {'detail': 'Tài khoản hoặc mật khẩu không đúng.', 'code': 'AUTH_INVALID',
                 'attempts': n},
                status=status.HTTP_401_UNAUTHORIZED)

        services.clear_fail(username, ip)
        AuditLog.record(user=user, action='login', entity='accounts.User',
                        entity_id=user.id, via='ui', ip=ip)
        tokens = _tokens_for(user)
        return Response({**tokens, 'user': UserSerializer(user).data})


class RefreshView(TokenRefreshView):
    """simplejwt rotation; ROTATE_REFRESH_TOKENS + BLACKLIST cấu hình ở settings."""
    permission_classes = [AllowAny]


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        """Tự quản lý tài khoản của chính mình: sửa hồ sơ + đổi mật khẩu.
        KHÔNG cho tự đổi role/quyền (đó là việc của admin)."""
        u = request.user
        for f in ('display_name', 'phone', 'email'):
            if f in request.data:
                setattr(u, f, str(request.data[f]).strip())
        pwd = request.data.get('password')
        if pwd:
            if len(str(pwd)) < 6:
                return Response({'detail': 'Mật khẩu tối thiểu 6 ký tự.'}, status=400)
            u.set_password(str(pwd))
        u.save()
        return Response(UserSerializer(u).data)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get('refresh')
        if token:
            try:
                RefreshToken(token).blacklist()
            except Exception:
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class JWKSView(APIView):
    """Public key cho sidecar (B.1 §8). RS256 → xuất JWK; HS256 → keys rỗng."""
    permission_classes = [AllowAny]

    def get(self, request):
        cfg = getattr(settings, 'SIMPLE_JWT', {})
        verifying_key = cfg.get('VERIFYING_KEY')
        alg = cfg.get('ALGORITHM', 'HS256')
        if alg == 'RS256' and verifying_key:
            try:
                import json
                from cryptography.hazmat.primitives.serialization import load_pem_public_key
                from jwt.algorithms import RSAAlgorithm
                public_key = load_pem_public_key(verifying_key.encode())
                jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
                jwk.update({'use': 'sig', 'alg': 'RS256',
                            'kid': cfg.get('JWT_KID', 'default')})
                return Response({'keys': [jwk]})
            except Exception:
                pass
        return Response({'keys': []})


class AssignableEngineersView(APIView):
    """Danh sách kỹ sư dịch vụ (+ quản lý) để giao ticket — nhân viên nội bộ xem được."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = User.objects.filter(role__in=[Role.SERVICE, Role.MANAGER], is_active=True).order_by('username')
        return Response([{'id': str(u.id), 'name': u.display_name or u.username, 'role': u.role}
                         for u in qs])


class IsSystemAdmin(BasePermission):
    """Quản trị người dùng: chỉ superuser hoặc role 'admin'."""
    message = 'Chỉ quản trị viên hệ thống (admin) được quản lý người dùng.'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_superuser or role_of(u) == Role.ADMIN))


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('username')
    permission_classes = [IsSystemAdmin]

    def get_serializer_class(self):
        return UserSerializer if self.action in ('list', 'retrieve') else UserWriteSerializer

    def perform_destroy(self, instance):
        # Tránh tự xóa mình → mất quyền quản trị; FE nên dùng "khóa" (is_active) thay vì xóa.
        if instance.id == self.request.user.id:
            raise ValidationError('Không thể xóa tài khoản của chính bạn.')
        instance.delete()

    @action(detail=True, methods=['post'], url_path='set-role')
    def set_role(self, request, pk=None):
        user = self.get_object()
        ser = SetRoleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_role = ser.validated_data['role']
        # Chặn tự hạ quyền admin của chính mình (tránh khóa cứng hệ thống).
        if user.id == request.user.id and new_role != Role.ADMIN and not request.user.is_superuser:
            return Response({'detail': 'Không thể tự bỏ quyền admin của chính mình.'}, status=400)
        before = user.role
        user.role = new_role
        user.save(update_fields=['role'])
        AuditLog.record(user=request.user, action='set_role', entity='accounts.User',
                        entity_id=user.id, diff={'before': before, 'after': user.role},
                        ip=_ip(request))
        return Response(UserSerializer(user).data)
