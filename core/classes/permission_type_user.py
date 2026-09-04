from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import NotAuthenticated, PermissionDenied


def raise_not_authenticated():
    """401: não há sessão válida. O front limpa o token e volta para o login."""
    raise NotAuthenticated(
        {
            "success": False,
            "status": status.HTTP_401_UNAUTHORIZED,
            "message": "Sessão expirada. Faça login novamente.",
            "data": {},
            "error": {},
        }
    )


def raise_permission_denied(message="Sem permissão para acessar o recurso."):
    """403: a sessão é válida, o acesso é que não. O front avisa e mantém o usuário logado."""
    raise PermissionDenied(
        {
            "success": False,
            "status": status.HTTP_403_FORBIDDEN,
            "message": message,
            "data": {},
            "error": {},
        }
    )


class TypePermissionClass(BasePermission):
    """Libera o acesso conforme o `User.type`. `allowed_types = None` aceita qualquer tipo."""

    allowed_types = None

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            raise_not_authenticated()

        if self.allowed_types is not None and user.type not in self.allowed_types:
            raise_permission_denied()

        return True


class AdminPermissionClass(TypePermissionClass):
    allowed_types = ["ADMIN"]


class UserPermissionClass(TypePermissionClass):
    allowed_types = ["USER", "BROKER"]


class AllPermissionClass(TypePermissionClass):
    allowed_types = ["ADMIN", "USER", "BROKER"]
