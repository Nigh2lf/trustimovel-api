import re

from django.db import transaction
from rest_framework import serializers
from drf_base64.fields import Base64ImageField
from core.models import User, UserPermission
from core.resources import (
    RESOURCE_KEYS,
    RESOURCE_MAP,
    USERS_RESOURCE,
    AccessLevel,
    max_level_for,
)


def permission_map(user):
    """Mapa completo {recurso: nível}, com os recursos sem concessão explícita em zero.

    Devolver o catálogo inteiro poupa o front de tratar chave ausente: o que não veio
    é Sem acesso, e o que veio é o nível.
    """
    if user.type == User.Type.ADMIN:
        return {key: int(AccessLevel.FULL) for key in RESOURCE_KEYS}

    granted = user.permission_map

    return {key: int(granted.get(key, AccessLevel.NO_ACCESS)) for key in RESOURCE_KEYS}


class PermissionMapField(serializers.Field):
    """Permissões como um dicionário {recurso: nível}, e não uma lista de objetos.

    A tela edita um select por recurso, então o formato de dicionário é o que ela já tem
    em mãos — evita o vai-e-vem de montar e desmontar lista dos dois lados.

    O `source` fica no default (`permissions`, o related_name), e não em `'*'`: com `'*'`
    o DRF espalha o dicionário na raiz de `validated_data` em vez de guardá-lo sob a
    chave, e a gravação passa direto sem gravar nada.
    """

    def to_representation(self, manager):
        granted = {
            permission.resource: permission.level for permission in manager.all()
        }

        return {key: int(granted.get(key, AccessLevel.NO_ACCESS)) for key in RESOURCE_KEYS}

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError('Envie um objeto no formato {recurso: nível}.')

        cleaned = {}

        for resource, level in data.items():
            if resource not in RESOURCE_MAP:
                raise serializers.ValidationError(f'Recurso desconhecido: {resource}.')

            try:
                level = int(level)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    f'Nível inválido para {RESOURCE_MAP[resource].label}.'
                )

            if level not in AccessLevel.values:
                raise serializers.ValidationError(
                    f'Nível inválido para {RESOURCE_MAP[resource].label}.'
                )

            ceiling = max_level_for(resource)
            if level > ceiling:
                raise serializers.ValidationError(
                    f'{RESOURCE_MAP[resource].label} é uma tela de consulta: '
                    f'o máximo é {AccessLevel(ceiling).label}.'
                )

            cleaned[resource] = level

        return cleaned


class UserSerializer(serializers.ModelSerializer):
    """Perfil do próprio usuário: o que `/users/profile/` devolve e o que ele edita de si."""

    profile_image = Base64ImageField(required=False)
    old_password = serializers.CharField(write_only=True, required=False)
    # No perfil o mapa passa por `permission_map`, que aplica o atalho do ADMIN da
    # plataforma — ele tem tudo sem precisar de linha gravada.
    permissions = serializers.SerializerMethodField()

    def get_permissions(self, user):
        return permission_map(user)

    def create(self, validated_data):
        password = validated_data.pop("password")

        validated_data["is_active"] = True
        validated_data["is_admin"] = False

        user = User.objects.create(**validated_data)
        user.set_password(password)
        user.save()

        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        old_password = validated_data.pop("old_password", None)

        if password is not None and not instance.check_password(old_password):
            raise serializers.ValidationError({"detail": "Senha incorreta!"})
        if password is not None:
            instance.set_password(password)

        return super().update(instance, validated_data)

    class Meta:
        model = User
        fields = [
            "id",
            "profile_image",
            "email",
            "name",
            "password",
            "old_password",
            "is_admin",
            "is_active",
            "type",
            "permissions",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "password": {"write_only": True},
            "old_password": {"write_only": True},
        }
        # Campos que o cliente nunca deve conseguir definir diretamente (privilégio, estado interno).
        read_only_fields = (
            "id",
            "is_admin",
            "is_active",
            "type",
            "created_at",
            "updated_at",
        )


class AgencyUserSerializer(serializers.ModelSerializer):
    """Gestão de usuários da imobiliária, feita por quem tem Total em Usuários.

    Diferente do `UserSerializer`, aqui um usuário mexe em **outro**: não pede a senha
    antiga para redefinir, e grava o mapa de permissões junto.
    """

    permissions = PermissionMapField(required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    # Só USER e BROKER: um gestor de imobiliária não promove ninguém a ADMIN da plataforma.
    type = serializers.ChoiceField(choices=[User.Type.USER, User.Type.BROKER], required=False)
    type_label = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "name",
            "password",
            "is_active",
            "type",
            "type_label",
            "team",
            "in_queue",
            "permissions",
            "created_at",
            "updated_at",
        ]
        # `is_active` é editável para poder desativar um funcionário.
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_email(self, value):
        query = User.objects.filter(email__iexact=value, deleted_at__isnull=True)

        if self.instance is not None:
            query = query.exclude(pk=self.instance.pk)

        if query.exists():
            raise serializers.ValidationError('Já existe um usuário com este e-mail.')

        return value

    def validate_password(self, value):
        # Em branco na edição significa "manter a senha atual".
        if not value:
            return value

        if len(value) < 8:
            raise serializers.ValidationError('A senha precisa ter ao menos 8 caracteres.')

        if not re.search(r'[A-Za-z]', value):
            raise serializers.ValidationError('A senha precisa ter ao menos uma letra.')

        if not re.search(r'\d', value):
            raise serializers.ValidationError('A senha precisa ter ao menos um número.')

        if not re.search(r'[^A-Za-z0-9]', value):
            raise serializers.ValidationError(
                'A senha precisa ter ao menos um caractere especial (ex.: ! @ # $ %).'
            )

        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': 'Informe a senha inicial.'})

        self._check_lockout(attrs)

        return attrs

    def _check_lockout(self, attrs):
        """Impede que a imobiliária fique sem ninguém capaz de administrar usuários."""
        request = self.context.get('request')
        actor = getattr(request, 'user', None)

        if self.instance is None or actor is None:
            return

        permissions = attrs.get('permissions')

        if permissions is None or USERS_RESOURCE not in permissions:
            return

        new_level = permissions[USERS_RESOURCE]

        if new_level >= AccessLevel.FULL:
            return

        # Rebaixar a si mesmo em Usuários é o jeito mais fácil de se trancar para fora.
        if self.instance.pk == actor.pk:
            raise serializers.ValidationError(
                {'permissions': 'Você não pode reduzir a sua própria permissão em Usuários.'}
            )

        remaining = (
            UserPermission.objects.filter(
                user__agency_id=self.instance.agency_id,
                user__deleted_at__isnull=True,
                user__is_active=True,
                resource=USERS_RESOURCE,
                level=AccessLevel.FULL,
            )
            .exclude(user_id=self.instance.pk)
            .exists()
        )

        if not remaining:
            raise serializers.ValidationError(
                {
                    'permissions': 'Este é o último usuário com acesso total a Usuários. '
                    'Dê o acesso a outra pessoa antes de reduzir o dele.'
                }
            )

    @transaction.atomic
    def create(self, validated_data):
        permissions = validated_data.pop('permissions', {})
        password = validated_data.pop('password')

        user = User(**validated_data)
        user.set_password(password)
        user.save()

        self._save_permissions(user, permissions)

        return user

    @transaction.atomic
    def update(self, instance, validated_data):
        permissions = validated_data.pop('permissions', None)
        password = validated_data.pop('password', None)

        for field, value in validated_data.items():
            setattr(instance, field, value)

        if password:
            instance.set_password(password)

        instance.save()

        if permissions is not None:
            self._save_permissions(instance, permissions)

        return instance

    def _save_permissions(self, user, permissions):
        for resource, level in permissions.items():
            UserPermission.objects.update_or_create(
                user=user, resource=resource, defaults={'level': level}
            )

        # O mapa foi lido antes da gravação; sem limpar, a resposta sairia desatualizada.
        if hasattr(user, '_permission_map'):
            del user._permission_map
