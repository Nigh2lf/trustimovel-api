"""Concessão de permissões em bloco, usada no nascimento de um usuário."""

from core.models import UserPermission
from core.resources import RESOURCES, AccessLevel


def grant_full_access(user):
    """Dá ao usuário o nível máximo de cada recurso.

    Telas de consulta param em Leitura, que já é o teto delas. Serve para o dono da conta:
    o primeiro usuário de uma imobiliária precisa alcançar Usuários para poder distribuir
    as permissões dos colegas, caso contrário a conta nasce trancada.
    """
    for resource in RESOURCES:
        level = AccessLevel.READ if resource.read_only else AccessLevel.FULL

        UserPermission.objects.update_or_create(
            user=user, resource=resource.key, defaults={'level': level}
        )

    if hasattr(user, '_permission_map'):
        del user._permission_map
