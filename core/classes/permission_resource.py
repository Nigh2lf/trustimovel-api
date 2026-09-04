from rest_framework.permissions import BasePermission

from core.classes.permission_type_user import raise_not_authenticated, raise_permission_denied
from core.resources import (
    ACTION_LEVELS,
    DEFAULT_ACTION_LEVEL,
    METHOD_LEVELS,
    RESOURCE_MAP,
    AccessLevel,
)


class ResourcePermission(BasePermission):
    """Exige do usuário o nível correspondente à action, no recurso declarado pelo ViewSet.

    A escada é `list`/`retrieve` → Visualizar, escrita → Criar/Editar, `destroy` → Acesso total.
    Uma @action customizada declara o nível dela com `@requires_level(...)`; sem declaração
    ela é tratada como escrita, que é o palpite conservador para um endpoint que faz POST.

    ViewSet sem `resource` **nega** o acesso. Endpoint novo que esqueça de declarar aparece
    como erro visível em vez de virar um buraco aberto sem ninguém notar.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            raise_not_authenticated()

        resource = getattr(view, 'resource', None)

        if resource not in RESOURCE_MAP:
            raise_permission_denied(
                'Recurso não configurado para este endpoint. Avise o suporte.'
            )

        required = self._required_level(request, view)

        if not user.can(resource, required):
            raise_permission_denied(self._message(resource, required))

        return True

    def _required_level(self, request, view):
        action = getattr(view, 'action', None)

        # APIView simples (o dashboard, por exemplo) não tem `action`: vale o método HTTP.
        if action is None:
            return METHOD_LEVELS.get(request.method, DEFAULT_ACTION_LEVEL)

        if action in ACTION_LEVELS:
            return ACTION_LEVELS[action]

        # @action customizada: o nível é o que ela declarou com @requires_level. Sem
        # declaração, assume escrita — o palpite conservador para um endpoint extra.
        handler = getattr(view, action, None)

        return getattr(handler, 'required_level', DEFAULT_ACTION_LEVEL)

    def _message(self, resource, required):
        label = RESOURCE_MAP[resource].label

        if required == AccessLevel.READ:
            return f'Você não tem acesso a {label}.'

        if required == AccessLevel.FULL:
            return f'Você não tem permissão para excluir em {label}.'

        return f'Você não tem permissão para alterar {label}.'
