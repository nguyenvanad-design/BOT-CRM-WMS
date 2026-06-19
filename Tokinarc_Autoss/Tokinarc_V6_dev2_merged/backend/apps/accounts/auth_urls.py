"""Auth endpoints (login/refresh/me/logout)."""
from django.urls import path
from .views import LoginView, RefreshView, MeView, LogoutView

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('refresh/', RefreshView.as_view(), name='refresh'),
    path('me/', MeView.as_view(), name='me'),
    path('logout/', LogoutView.as_view(), name='logout'),
]
