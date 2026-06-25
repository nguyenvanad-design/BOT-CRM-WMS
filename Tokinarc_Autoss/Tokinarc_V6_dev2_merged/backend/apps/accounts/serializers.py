"""
Tokinarc V6.C — apps/accounts/serializers.py
"""
from __future__ import annotations

from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    is_admin  = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = ['id', 'username', 'display_name', 'full_name', 'email',
                  'phone', 'role', 'customer', 'is_active', 'is_admin', 'date_joined']
        read_only_fields = ['id', 'date_joined']

    def get_full_name(self, obj) -> str:
        return obj.display_name or obj.get_full_name() or obj.username

    def get_is_admin(self, obj) -> bool:
        """Quản trị hệ thống: superuser hoặc role 'admin' — dùng để FE hiện tab Quản trị."""
        return bool(obj.is_superuser or obj.role == 'admin')


class UserWriteSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model  = User
        fields = ['id', 'username', 'display_name', 'email', 'phone',
                  'role', 'customer', 'is_active', 'password']
        read_only_fields = ['id']

    def create(self, validated_data):
        pwd = validated_data.pop('password', None)
        user = User(**validated_data)
        if pwd:
            user.set_password(pwd)
        user.save()
        return user

    def update(self, instance, validated_data):
        pwd = validated_data.pop('password', None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        if pwd:
            instance.set_password(pwd)
        instance.save()
        return instance


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class SetRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=User._meta.get_field('role').choices)
