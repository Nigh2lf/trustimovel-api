"""
Catálogo de recursos do painel da imobiliária e os níveis de acesso a eles.

Um recurso é uma tela do menu lateral, e é a mesma chave dos dois lados: o ViewSet declara
`resource = "imoveis"` e o item de menu do front declara `"imoveis"`. É o que amarra menu,
rota e endpoint no mesmo nome.

O catálogo mora aqui, no código, e não numa tabela: um recurso só existe se a tela e o
endpoint existem, e isso chega por deploy, não por INSERT. O banco guarda as concessões
(`UserPermission`), não o catálogo.

Ao acrescentar uma tela nova ao menu, acrescente o recurso aqui e declare `resource` no
ViewSet correspondente. ViewSet sem `resource` nega o acesso, em vez de liberar.
"""

from collections import namedtuple

from django.db import models


class AccessLevel(models.IntegerChoices):
    """Níveis progressivos: o valor é ordinal de propósito, a checagem é `nivel >= exigido`.

    Estes rótulos são a nomenclatura oficial e saem daqui para a tela pelo endpoint
    `/users/permission-resources/` — o front não mantém uma lista própria.
    """

    NO_ACCESS = 0, 'Sem acesso'
    READ = 1, 'Visualizar'
    WRITE = 2, 'Criar/Editar'
    FULL = 3, 'Acesso total'


# Nível exigido por action do ModelViewSet. Uma @action customizada declara o dela com
# o decorator `requires_level`; sem declaração, cai no padrão de escrita.
ACTION_LEVELS = {
    'list': AccessLevel.READ,
    'retrieve': AccessLevel.READ,
    'create': AccessLevel.WRITE,
    'update': AccessLevel.WRITE,
    'partial_update': AccessLevel.WRITE,
    'destroy': AccessLevel.FULL,
}

DEFAULT_ACTION_LEVEL = AccessLevel.WRITE

# Fallback para APIView simples, que não tem `action` — o dashboard, por exemplo.
METHOD_LEVELS = {
    'GET': AccessLevel.READ,
    'HEAD': AccessLevel.READ,
    'OPTIONS': AccessLevel.READ,
    'POST': AccessLevel.WRITE,
    'PUT': AccessLevel.WRITE,
    'PATCH': AccessLevel.WRITE,
    'DELETE': AccessLevel.FULL,
}


ResourceDef = namedtuple('ResourceDef', 'key label group read_only')


def _resource(key, label, group, read_only=False):
    return ResourceDef(key, label, group, read_only)


# A ordem daqui é a ordem que o front usa para montar a tela de permissões.
# `read_only=True` marca tela de consulta: só faz sentido Sem acesso ou Leitura.
RESOURCES = [
    _resource('dashboard', 'Dashboard', 'Dashboard', read_only=True),

    _resource('leads', 'Leads', 'CRM'),
    _resource('fila', 'Fila de Atendimento', 'CRM'),
    _resource('atendimentos', 'Atendimentos', 'CRM'),
    _resource('tarefas', 'Tarefas & Agenda', 'CRM'),
    _resource('funil', 'Funil de Vendas', 'CRM'),

    _resource('imoveis', 'Imóveis', 'Imóveis'),

    _resource('condominios', 'Condomínios', 'Condomínios'),

    _resource('clientes', 'Clientes', 'Pessoas'),
    _resource('proprietarios', 'Proprietários', 'Pessoas'),
    _resource('corretores', 'Corretores', 'Pessoas'),

    _resource('blog', 'Blog', 'Marketing'),
    _resource('blog_categorias', 'Categorias do Blog', 'Marketing'),
    _resource('banners', 'Banners', 'Marketing'),
    _resource('empresa', 'Empresa', 'Marketing'),

    # "Exportadores" e "Portais/Exportadores" são duas telas da mesma configuração
    # (`/agency-exporters/`), por isso dividem um recurso só. Separá-las criaria a
    # combinação quebrada de ver o menu e receber 403 em tudo dentro dele.
    _resource('exportadores', 'Exportadores e Portais', 'Integrações'),

    _resource('relatorios', 'Relatórios', 'Relatórios', read_only=True),

    _resource('usuarios', 'Usuários & Permissões', 'Administração'),
    _resource('configuracoes', 'Configurações do Sistema', 'Administração'),
]

RESOURCE_MAP = {resource.key: resource for resource in RESOURCES}

RESOURCE_KEYS = [resource.key for resource in RESOURCES]

RESOURCE_CHOICES = [(resource.key, resource.label) for resource in RESOURCES]

# Quem administra usuários administra também as permissões de todo mundo. É o recurso
# que fecha o ciclo, por isso as travas anti-lockout olham para ele.
USERS_RESOURCE = 'usuarios'


def max_level_for(resource_key):
    """Teto do recurso: telas de consulta não passam de Leitura."""
    resource = RESOURCE_MAP.get(resource_key)

    if resource is not None and resource.read_only:
        return AccessLevel.READ

    return AccessLevel.FULL


def requires_level(level):
    """Declara o nível exigido por uma @action customizada.

    Uso:
        @action(detail=True, methods=["post"])
        @requires_level(AccessLevel.WRITE)
        def reordenar(self, request, pk=None):
    """

    def decorator(func):
        func.required_level = level
        return func

    return decorator
