import re
import urllib.parse
from datetime import timedelta
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from core.models import User, UserPermission
from core.serializers import (
    AgencyUserSerializer,
    UserSerializer,
    ForgotPasswordSerializer,
    ChangePasswordForgotSerializer,
)
from core.classes.base_viewset import BaseViewSet
from core.services import send_email_forgot_password
from core.classes.permission_resource import ResourcePermission
from core.classes.permission_type_user import AllPermissionClass, raise_permission_denied
from core.resources import RESOURCES, USERS_RESOURCE, AccessLevel, requires_level
from config.settings import URL_FORGOT_PASSWORD

class UserViewSet(BaseViewSet):
    """Gestão dos usuários da imobiliária, governada pelo recurso `usuarios`.

    Quem tem Total em Usuários administra a equipe da própria imobiliária — não existe
    um papel de gestor separado, a permissão no recurso é o papel.
    """

    serializer_class = AgencyUserSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, AllPermissionClass, ResourcePermission]
    resource = USERS_RESOURCE
    search_fields = ["email", "name"]
    filter_backends = (SearchFilter, OrderingFilter)
    ordering_fields = ("name", "email", "is_active", "created_at")
    ordering = ("name", "email")

    def get_permissions(self):
        if self.action in ["forgot_password", "change_password_forgot_password"]:
            return [permissions.AllowAny()]

        # Ver e editar os próprios dados independe de permissão em Usuários.
        if self.action == "profile":
            return [permissions.IsAuthenticated()]

        return [
            permissions.IsAuthenticated(),
            AllPermissionClass(),
            ResourcePermission(),
        ]

    def get_serializer_class(self):
        if self.action == "profile":
            return UserSerializer

        return AgencyUserSerializer

    def get_queryset(self):
        queryset = User.objects.filter(deleted_at__isnull=True).prefetch_related("permissions")

        # O ADMIN da plataforma administra qualquer conta; o usuário da imobiliária só
        # enxerga os colegas. Sem este filtro a listagem vazaria usuários de outros clientes.
        if self.request.user.type == User.Type.ADMIN:
            return queryset

        return queryset.filter(agency_id=self.request.user.agency_id)

    def perform_create(self, serializer):
        # A imobiliária vem do token, nunca do corpo da requisição.
        serializer.save(agency_id=self.request.user.agency_id)

    def perform_destroy(self, instance):
        if instance.pk == self.request.user.pk:
            raise_permission_denied('Você não pode excluir o seu próprio usuário.')

        self._guard_last_manager(instance)

        instance.delete(deleted_by=self.request.user)

    def _guard_last_manager(self, instance):
        """Excluir o último usuário com Total em Usuários trancaria a imobiliária para fora."""
        is_manager = UserPermission.objects.filter(
            user=instance, resource=USERS_RESOURCE, level=AccessLevel.FULL
        ).exists()

        if not is_manager:
            return

        remaining = (
            UserPermission.objects.filter(
                user__agency_id=instance.agency_id,
                user__deleted_at__isnull=True,
                user__is_active=True,
                resource=USERS_RESOURCE,
                level=AccessLevel.FULL,
            )
            .exclude(user_id=instance.pk)
            .exists()
        )

        if not remaining:
            raise_permission_denied(
                'Este é o último usuário com acesso total a Usuários. '
                'Dê o acesso a outra pessoa antes de excluí-lo.'
            )

    @action(detail=False, methods=["get"], url_path="profile")
    def profile(self, request):
        serializer = self.get_serializer(request.user)
        return self._response_format(True, status.HTTP_200_OK, data=serializer.data)

    @action(detail=False, methods=["get"], url_path="permission-resources")
    @requires_level(AccessLevel.READ)
    def permission_resources(self, request):
        """Catálogo que a tela de permissões usa para montar um select por recurso."""
        return self._response_format(
            True,
            status.HTTP_200_OK,
            data={
                "resources": [
                    {
                        "key": resource.key,
                        "label": resource.label,
                        "group": resource.group,
                        "read_only": resource.read_only,
                    }
                    for resource in RESOURCES
                ],
                "levels": [
                    {"value": int(level), "label": level.label} for level in AccessLevel
                ],
            },
        )

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[permissions.AllowAny],
        url_path="forgot-password",
    )
    def forgot_password(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            user = None

        # Resposta genérica em qualquer caso, para não permitir enumeração de e-mails cadastrados.
        if user is not None:
            now = timezone.now()
            user.forgot_password_hash = re.sub(r"\D", "", str(now))
            user.forgot_password_expire = now + timedelta(hours=24)
            user.save()

            link = "%s?email=%s&hash=%s" % (
                URL_FORGOT_PASSWORD,
                urllib.parse.quote(user.email),
                user.forgot_password_hash,
            )
            send_email_forgot_password(user.email, user.name, link)

        return Response(
            {"detail": "Se o e-mail estiver cadastrado, enviaremos um link de recuperação."}
        )

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[permissions.AllowAny],
        url_path="change-password-forgot-password",
    )
    def change_password_forgot_password(self, request):
        serializer = ChangePasswordForgotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        try:
            user = User.objects.get(
                email=data["email"], forgot_password_hash=data["forgot_password_hash"]
            )
        except User.DoesNotExist:
            return Response(
                {"detail": "Erro: Usuário ou Hash inválidos"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        if user.forgot_password_expire < now:
            return Response(
                {"detail": "Expire time forgot password"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(data["new_password"])
        user.forgot_password_expire = now
        user.save()

        return Response({"worked": True})

