"""
Tokinarc V6 — apps/crm/contacts.py

Endpoint list/CRUD người liên hệ PHẲNG (Contact vốn lồng trong Customer).
Tôn trọng ownership: sale chỉ thấy liên hệ của KH mình; manager/admin thấy hết.

GET/POST/PATCH/DELETE /api/v1/crm/contacts/
"""
from __future__ import annotations

from rest_framework import filters, serializers, viewsets

from apps.accounts.roles import is_manager

from .models import Contact
from .permissions import IsAuthenticatedWithRole


class ContactFlatSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_code = serializers.CharField(source='customer.code', read_only=True)

    class Meta:
        model = Contact
        fields = [
            'id', 'customer', 'customer_name', 'customer_code',
            'full_name', 'title', 'phone', 'email',
            'preferred_channel', 'is_primary', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactFlatSerializer
    permission_classes = [IsAuthenticatedWithRole]
    filter_backends = [filters.SearchFilter]
    search_fields = ['full_name', 'phone', 'email', 'customer__name']

    def get_queryset(self):
        qs = Contact.objects.select_related('customer')
        u = self.request.user
        if not is_manager(u):
            qs = qs.filter(customer__owner_id=u.id)
        return qs
