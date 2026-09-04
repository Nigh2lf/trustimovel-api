import json
import logging
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, F, Max, Min, OuterRef, Q, Subquery, Sum
from django.utils import timezone

from core.models import (
    AssistantConversation,
    AssistantMessage,
    BlogPost,
    Broker,
    City,
    Client,
    Condominium,
    Deal,
    Lead,
    Neighborhood,
    Owner,
    Property,
    PropertyPrice,
    PropertyType,
    ServiceTicket,
    SiteBanner,
    State,
    Task,
)
from core.resources import AccessLevel

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6

HISTORY_LIMIT = 20

DEFAULT_LIST_LIMIT = 10

MAX_LIST_LIMIT = 20

WEEKDAYS = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo']


class AssistantError(Exception):
    """Falha na conversa com o Grok, com mensagem pronta para o usuário."""


ENTITIES = {
    'properties': {
        'model': Property,
        'resource': 'imoveis',
        'label': 'Imóveis',
        'fields': ('code', 'name', 'broker__name', 'is_active', 'on_site', 'created_at'),
        'search_fields': ('code', 'name', 'address'),
        'responsible_field': 'broker__name',
        'key_field': 'code',
        'group_by': {
            'type': 'type__name',
            'neighborhood': 'neighborhood__name',
            'city': 'neighborhood__city__name',
            'broker': 'broker__name',
        },
    },
    'condominiums': {
        'model': Condominium,
        'resource': 'condominios',
        'label': 'Condomínios',
        'fields': ('name', 'address', 'created_at'),
        'search_fields': ('name', 'address'),
        'group_by': {},
    },
    'brokers': {
        'model': Broker,
        'resource': 'corretores',
        'label': 'Corretores',
        'fields': ('name', 'email', 'phone', 'created_at'),
        'search_fields': ('name', 'email'),
        'group_by': {},
    },
    'owners': {
        'model': Owner,
        'resource': 'proprietarios',
        'label': 'Proprietários',
        'fields': ('name', 'email', 'phone', 'created_at'),
        'search_fields': ('name', 'email', 'phone'),
        'group_by': {},
    },
    'clients': {
        'model': Client,
        'resource': 'clientes',
        'label': 'Clientes',
        'fields': ('code', 'name', 'type', 'phone', 'created_at'),
        'search_fields': ('code', 'name', 'email', 'phone'),
        'key_field': 'code',
        'group_by': {'type': 'type'},
        'choices': {'type': Client.Type.choices},
    },
    'leads': {
        'model': Lead,
        'resource': 'leads',
        'label': 'Leads',
        'fields': ('code', 'name', 'status', 'source', 'interest', 'responsible__name', 'last_contact_at', 'created_at'),
        'search_fields': ('code', 'name', 'email', 'phone'),
        'responsible_field': 'responsible__name',
        'key_field': 'code',
        'group_by': {
            'status': 'status',
            'source': 'source',
            'interest': 'interest',
            'responsible': 'responsible__name',
        },
        'choices': {
            'status': Lead.Status.choices,
            'source': Lead.Source.choices,
            'interest': Lead.Interest.choices,
        },
    },
    'service_tickets': {
        'model': ServiceTicket,
        'resource': 'atendimentos',
        'label': 'Atendimentos',
        'fields': ('protocol', 'client_name', 'subject', 'status', 'priority', 'responsible__name', 'created_at'),
        'search_fields': ('protocol', 'client_name', 'subject', 'property_code'),
        'responsible_field': 'responsible__name',
        'key_field': 'protocol',
        'group_by': {
            'status': 'status',
            'category': 'category',
            'priority': 'priority',
            'responsible': 'responsible__name',
        },
        'choices': {
            'status': ServiceTicket.Status.choices,
            'category': ServiceTicket.Category.choices,
            'priority': ServiceTicket.Priority.choices,
        },
    },
    'tasks': {
        'model': Task,
        'resource': 'tarefas',
        'label': 'Tarefas',
        'fields': ('title', 'type', 'status', 'priority', 'due_date', 'due_time', 'responsible__name', 'created_at'),
        'search_fields': ('title', 'property_code'),
        'responsible_field': 'responsible__name',
        'group_by': {
            'status': 'status',
            'type': 'type',
            'priority': 'priority',
            'responsible': 'responsible__name',
        },
        'choices': {
            'status': Task.Status.choices,
            'type': Task.Type.choices,
            'priority': Task.Priority.choices,
        },
    },
    'deals': {
        'model': Deal,
        'resource': 'funil',
        'label': 'Funil de Vendas',
        'fields': ('title', 'client_name', 'stage', 'value', 'outcome', 'responsible__name', 'closed_at', 'created_at'),
        'search_fields': ('title', 'client_name', 'property_code'),
        'responsible_field': 'responsible__name',
        'group_by': {
            'stage': 'stage',
            'outcome': 'outcome',
            'type': 'type',
            'responsible': 'responsible__name',
        },
        'choices': {
            'stage': Deal.Stage.choices,
            'outcome': Deal.Outcome.choices,
            'type': Deal.Type.choices,
        },
    },
    'blog_posts': {
        'model': BlogPost,
        'resource': 'blog',
        'label': 'Blog',
        'fields': ('title', 'status', 'published_at', 'created_at'),
        'search_fields': ('title',),
        'group_by': {'status': 'status'},
        'choices': {'status': BlogPost.Status.choices},
    },
    'site_banners': {
        'model': SiteBanner,
        'resource': 'banners',
        'label': 'Banners',
        'fields': ('title', 'is_active', 'created_at'),
        'search_fields': ('title',),
        'group_by': {},
    },
}

TOOL_SCHEMAS = [
    {
        'type': 'function',
        'function': {
            'name': 'query_records',
            'description': (
                'Conta ou lista registros da imobiliária. Entidades: properties (imóveis), '
                'condominiums (condomínios), brokers (corretores), owners (proprietários), '
                'clients (clientes), leads, service_tickets (atendimentos), tasks (tarefas), '
                'deals (negócios do funil de vendas), blog_posts (matérias do blog), '
                'site_banners (banners do site). Valores aceitos em status por entidade — '
                'properties: ACTIVE, INACTIVE, ON_SITE, OFF_SITE, FEATURED, EXCLUSIVE, '
                'RESERVED, OPPORTUNITY, UNDER_CONSTRUCTION, WITHOUT_PHOTO; '
                'leads: NEW, IN_CONTACT, QUALIFIED, UNQUALIFIED, CONVERTED; '
                'service_tickets: NEW, IN_PROGRESS, AWAITING_RESPONSE, RESOLVED, CLOSED; '
                'tasks: PENDING, IN_PROGRESS, DONE; '
                'deals: etapas QUALIFICATION, VISIT_SCHEDULED, VISIT_DONE, PROPOSAL, '
                'NEGOTIATION, CLOSING ou desfechos WON, LOST; '
                'clients: BUYER, SELLER, TENANT, LANDLORD; '
                'blog_posts: DRAFT, PUBLISHED; site_banners: ACTIVE, INACTIVE. '
                'Para perguntas sobre preço de imóvel (mais caro, mais barato, preço médio), '
                'use purpose (SALE venda, RENT locação, SEASONAL temporada; padrão SALE) com '
                'order_by no list ou com count para receber os agregados de preço.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'entity': {'type': 'string', 'enum': list(ENTITIES)},
                    'operation': {
                        'type': 'string',
                        'enum': ['count', 'list'],
                        'description': 'count devolve totais; list devolve os registros mais recentes.',
                    },
                    'status': {
                        'type': 'string',
                        'description': 'Filtra pelo estado do registro; valores válidos na descrição da ferramenta.',
                    },
                    'created_from': {'type': 'string', 'description': 'Cadastrados a partir desta data, AAAA-MM-DD.'},
                    'created_to': {'type': 'string', 'description': 'Cadastrados até esta data, AAAA-MM-DD.'},
                    'overdue': {'type': 'boolean', 'description': 'Somente tasks: tarefas pendentes com prazo vencido.'},
                    'open_only': {
                        'type': 'boolean',
                        'description': 'service_tickets: só os não resolvidos; deals: só os ainda abertos.',
                    },
                    'group_by': {
                        'type': 'string',
                        'description': (
                            'Agrupa a contagem. properties: type, neighborhood, city, broker; '
                            'clients: type; leads: status, source, interest, responsible; '
                            'service_tickets: status, category, priority, responsible; '
                            'tasks: status, type, priority, responsible; '
                            'deals: stage, outcome, type, responsible; blog_posts: status.'
                        ),
                    },
                    'search': {
                        'type': 'string',
                        'description': 'Busca textual por código, nome, título, e-mail ou telefone, conforme a entidade.',
                    },
                    'responsible': {
                        'type': 'string',
                        'description': (
                            'Filtra pelo nome do corretor responsável (leads, service_tickets, '
                            'tasks, deals) ou do captador (properties).'
                        ),
                    },
                    'due_from': {'type': 'string', 'description': 'Somente tasks: prazo a partir desta data, AAAA-MM-DD.'},
                    'due_to': {'type': 'string', 'description': 'Somente tasks: prazo até esta data, AAAA-MM-DD.'},
                    'closed_from': {'type': 'string', 'description': 'Somente deals: fechados a partir desta data, AAAA-MM-DD.'},
                    'closed_to': {'type': 'string', 'description': 'Somente deals: fechados até esta data, AAAA-MM-DD.'},
                    'min_value': {'type': 'number', 'description': 'Somente deals: valor mínimo do negócio.'},
                    'max_value': {'type': 'number', 'description': 'Somente deals: valor máximo do negócio.'},
                    'min_price': {'type': 'number', 'description': 'Somente properties: preço mínimo na finalidade escolhida.'},
                    'max_price': {'type': 'number', 'description': 'Somente properties: preço máximo na finalidade escolhida.'},
                    'no_contact_days': {
                        'type': 'integer',
                        'description': 'Somente leads: sem nenhum contato há pelo menos N dias.',
                    },
                    'limit': {'type': 'integer', 'description': 'Máximo de registros no list (padrão 10, máximo 20).'},
                    'property_type': {
                        'type': 'string',
                        'description': 'Somente properties: filtra pelo tipo do imóvel (ex.: Apartamento, Casa).',
                    },
                    'neighborhood': {
                        'type': 'string',
                        'description': 'Somente properties: filtra pelo nome do bairro.',
                    },
                    'min_bedrooms': {
                        'type': 'integer',
                        'description': 'Somente properties: número mínimo de quartos.',
                    },
                    'purpose': {
                        'type': 'string',
                        'enum': ['SALE', 'RENT', 'SEASONAL'],
                        'description': 'Somente properties: finalidade do preço usada na ordenação e nos agregados.',
                    },
                    'order_by': {
                        'type': 'string',
                        'enum': ['price_desc', 'price_asc'],
                        'description': 'Somente properties: ordena pelo preço da finalidade escolhida (padrão venda).',
                    },
                },
                'required': ['entity', 'operation'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_record',
            'description': (
                'Detalhes completos de um registro específico, localizado por código, protocolo, '
                'nome ou título (ex.: imóvel 145, atendimento ATD-2026-001, lead LEAD023, '
                'cliente Maria). Imóvel vem com preços, taxas, infraestrutura, endereço e captador; '
                'lead vem com as últimas interações; atendimento vem com as últimas mensagens.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'entity': {'type': 'string', 'enum': list(ENTITIES)},
                    'query': {'type': 'string', 'description': 'Código, protocolo, nome ou título do registro.'},
                },
                'required': ['entity', 'query'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'dashboard_summary',
            'description': (
                'Resumo geral do painel: totais de imóveis, leads, negócios abertos do funil, '
                'tarefas de hoje e atrasadas e atendimentos abertos.'
            ),
            'parameters': {'type': 'object', 'properties': {}},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'sales_report',
            'description': (
                'Fechamentos do funil de vendas no período: negócios ganhos e perdidos '
                '(quantidade e valor) e taxa de conversão. Sem datas, considera o mês atual.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'start': {'type': 'string', 'description': 'Início do período, AAAA-MM-DD.'},
                    'end': {'type': 'string', 'description': 'Fim do período, AAAA-MM-DD.'},
                },
            },
        },
    },
]


def ask(*, user, text, conversation=None):
    """Responde a pergunta do usuário com o Grok e grava o par pergunta/resposta na conversa."""
    reply = _run_grok_loop(user, conversation, text)

    with transaction.atomic():
        if conversation is None:
            conversation = AssistantConversation.objects.create(
                agency_id=user.agency_id, user=user, title=text[:120]
            )

        AssistantMessage.objects.create(
            conversation=conversation, role=AssistantMessage.Role.USER, content=text
        )
        AssistantMessage.objects.create(
            conversation=conversation, role=AssistantMessage.Role.ASSISTANT, content=reply
        )
        # Toca o updated_at para a conversa mais ativa aparecer primeiro na listagem.
        conversation.save(update_fields=['updated_at'])

    return conversation, reply


def _run_grok_loop(user, conversation, text):
    messages = [{'role': 'system', 'content': _system_prompt(user)}]

    if conversation is not None:
        history = list(conversation.messages.order_by('-created_at')[:HISTORY_LIMIT])
        for message in reversed(history):
            role = 'user' if message.role == AssistantMessage.Role.USER else 'assistant'
            messages.append({'role': role, 'content': message.content})

    messages.append({'role': 'user', 'content': text})

    for _round in range(MAX_TOOL_ROUNDS):
        reply = _call_grok(messages)
        tool_calls = reply.get('tool_calls')

        if not tool_calls:
            content = (reply.get('content') or '').strip()

            if not content:
                raise AssistantError('O Theo não conseguiu montar uma resposta. Tente reformular a pergunta.')

            return content

        messages.append(
            {'role': 'assistant', 'content': reply.get('content'), 'tool_calls': tool_calls}
        )

        for tool_call in tool_calls:
            result = _run_tool(user, tool_call)
            messages.append(
                {
                    'role': 'tool',
                    'tool_call_id': tool_call.get('id'),
                    'content': json.dumps(result, ensure_ascii=False, default=str),
                }
            )

    # Rodadas esgotadas: uma última chamada sem ferramentas força a resposta com o que já foi consultado.
    logger.warning('Theo esgotou as rodadas de ferramenta; forçando a resposta final.')
    reply = _call_grok(messages, tool_choice='none')
    content = (reply.get('content') or '').strip()

    if content:
        return content

    raise AssistantError('A consulta ficou longa demais. Tente uma pergunta mais direta.')


def _system_prompt(user):
    today = timezone.localdate()

    return (
        f'Você é o Theo, assistente virtual do painel da imobiliária {user.agency.name}. '
        f'Hoje é {WEEKDAYS[today.weekday()]}, {today.strftime("%d/%m/%Y")}. '
        'Responda sempre em português do Brasil, de forma curta e direta. '
        'Use as ferramentas para consultar os dados reais da imobiliária antes de responder; '
        'nunca invente números. Ao interpretar períodos como "este mês" ou "esta semana", '
        'converta para datas concretas (a semana começa na segunda-feira) e diga qual período '
        'considerou. Se uma ferramenta retornar erro de permissão, explique que o usuário não '
        'tem acesso àquela área do painel. Valores monetários em reais (R$). '
        'Formate no máximo com **negrito** e listas com hífen ou números; não use '
        'tabelas, títulos nem outros recursos de Markdown. '
        'Quando o usuário citar um registro específico (um imóvel, um lead, um atendimento), '
        'use get_record para trazer os detalhes. '
        'Não responda assuntos que não sejam sobre os dados da imobiliária.'
    )


def _call_grok(messages, tools=None, tool_choice='auto'):
    body = json.dumps(
        {
            'model': settings.GROK_MODEL,
            'messages': messages,
            'tools': tools if tools is not None else TOOL_SCHEMAS,
            'tool_choice': tool_choice,
        }
    ).encode('utf-8')

    request = Request(
        settings.GROK_API_URL,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {settings.GROK_KEY_API}',
        },
    )

    try:
        with urlopen(request, timeout=settings.GROK_TIMEOUT) as response:
            payload = json.loads(response.read().decode('utf-8'))

        return payload['choices'][0]['message']
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.warning('Falha na chamada ao Grok: %s', exc)
        raise AssistantError('O Theo está indisponível no momento. Tente novamente em instantes.') from exc


def _run_tool(user, tool_call):
    function = tool_call.get('function', {})
    handler = TOOL_HANDLERS.get(function.get('name'))

    if handler is None:
        return {'error': 'Ferramenta desconhecida.'}

    try:
        arguments = json.loads(function.get('arguments') or '{}')
    except json.JSONDecodeError:
        return {'error': 'Argumentos inválidos.'}

    if not isinstance(arguments, dict):
        return {'error': 'Argumentos inválidos.'}

    result = handler(user, arguments)

    if isinstance(result, dict) and result.get('error'):
        logger.warning(
            'Theo: ferramenta %s com %s retornou erro: %s',
            function.get('name'), function.get('arguments'), result['error'],
        )

    return result


def _query_records(user, arguments):
    definition = ENTITIES.get(arguments.get('entity'))

    if definition is None:
        return {'error': 'Entidade desconhecida.'}

    if not user.can(definition['resource'], AccessLevel.READ):
        return {'error': f'Sem permissão para consultar {definition["label"]}.'}

    queryset = definition['model'].objects.filter(
        agency_id=user.agency_id, deleted_at__isnull=True
    )

    try:
        queryset = _apply_created_range(queryset, arguments)
    except ValueError:
        return {'error': 'Informe as datas no formato AAAA-MM-DD.'}

    status_value = arguments.get('status')
    if status_value:
        queryset = _apply_status(arguments['entity'], definition, queryset, status_value)

        if queryset is None:
            return {'error': f'Status inválido para {definition["label"]}.'}

    if arguments.get('search'):
        queryset = queryset.filter(_search_conditions(definition, arguments['search']))

    if arguments.get('responsible'):
        responsible_field = definition.get('responsible_field')

        if responsible_field is None:
            return {'error': f'{definition["label"]} não tem responsável para filtrar.'}

        queryset = queryset.filter(
            **{f'{responsible_field}__icontains': str(arguments['responsible']).strip()}
        )

    queryset, error = _apply_entity_filters(arguments.get('entity'), queryset, arguments)

    if error:
        return {'error': error}

    if arguments.get('overdue') and arguments.get('entity') == 'tasks':
        queryset = _only_overdue_tasks(queryset)

    if arguments.get('open_only'):
        if arguments.get('entity') == 'service_tickets':
            queryset = queryset.filter(
                status__in=[
                    ServiceTicket.Status.NEW,
                    ServiceTicket.Status.IN_PROGRESS,
                    ServiceTicket.Status.AWAITING_RESPONSE,
                ]
            )
        elif arguments.get('entity') == 'deals':
            queryset = queryset.filter(outcome__isnull=True)

    if arguments.get('entity') == 'properties':
        queryset, error = _apply_property_filters(queryset, arguments)

        if error:
            return {'error': error}

    # Agrupamento implica contagem, mesmo que o modelo peça list junto.
    if arguments.get('operation') == 'list' and not arguments.get('group_by'):
        return _list_result(definition, queryset, arguments)

    return _count_result(arguments.get('entity'), definition, queryset, arguments)


def _apply_created_range(queryset, arguments):
    created_from = arguments.get('created_from')
    created_to = arguments.get('created_to')

    if created_from:
        begin = timezone.make_aware(datetime.combine(date.fromisoformat(created_from), time.min))
        queryset = queryset.filter(created_at__gte=begin)

    if created_to:
        # Limite em datetime: o lookup __date dependeria do CONVERT_TZ do MySQL.
        finish = timezone.make_aware(
            datetime.combine(date.fromisoformat(created_to) + timedelta(days=1), time.min)
        )
        queryset = queryset.filter(created_at__lt=finish)

    return queryset


def _apply_status(entity, definition, queryset, status_value):
    status_value = str(status_value).strip().upper()

    if entity in ('properties', 'site_banners'):
        flags = {
            'ACTIVE': {'is_active': True},
            'INACTIVE': {'is_active': False},
        }
        if entity == 'properties':
            flags.update(
                {
                    'ON_SITE': {'on_site': True},
                    'OFF_SITE': {'on_site': False},
                    'FEATURED': {'featured': True},
                    'EXCLUSIVE': {'exclusive': True},
                    'RESERVED': {'reserved': True},
                    'OPPORTUNITY': {'opportunity': True},
                    'UNDER_CONSTRUCTION': {'under_construction': True},
                }
            )

            # Sem linha de foto ativa: o exclude tira quem tem pelo menos uma na galeria.
            if status_value == 'WITHOUT_PHOTO':
                return queryset.exclude(photos__deleted_at__isnull=True)

        if status_value not in flags:
            return None

        return queryset.filter(**flags[status_value])

    if entity == 'clients':
        return queryset.filter(type=status_value) if status_value in Client.Type.values else None

    if entity == 'deals':
        if status_value in Deal.Stage.values:
            return queryset.filter(stage=status_value)

        if status_value in Deal.Outcome.values:
            return queryset.filter(outcome=status_value)

        return None

    choices = definition.get('choices', {}).get('status')

    if choices is None or status_value not in dict(choices):
        return None

    return queryset.filter(status=status_value)


def _search_conditions(definition, term):
    term = str(term).strip()
    conditions = Q()

    for field in definition['search_fields']:
        conditions |= Q(**{f'{field}__icontains': term})

    return conditions


def _apply_entity_filters(entity, queryset, arguments):
    """Filtros que só existem para uma entidade específica."""
    try:
        if entity == 'tasks':
            if arguments.get('due_from'):
                queryset = queryset.filter(due_date__gte=date.fromisoformat(arguments['due_from']))

            if arguments.get('due_to'):
                queryset = queryset.filter(due_date__lte=date.fromisoformat(arguments['due_to']))

        if entity == 'deals':
            if arguments.get('closed_from'):
                queryset = queryset.filter(closed_at__gte=date.fromisoformat(arguments['closed_from']))

            if arguments.get('closed_to'):
                queryset = queryset.filter(closed_at__lte=date.fromisoformat(arguments['closed_to']))

            if arguments.get('min_value') is not None:
                queryset = queryset.filter(value__gte=float(arguments['min_value']))

            if arguments.get('max_value') is not None:
                queryset = queryset.filter(value__lte=float(arguments['max_value']))

        if entity == 'leads' and arguments.get('no_contact_days') is not None:
            cutoff = timezone.localdate() - timedelta(days=int(arguments['no_contact_days']))
            # Lead nunca contatado conta pela data de cadastro, senão o recém-criado apareceria como atrasado.
            created_cutoff = timezone.make_aware(
                datetime.combine(cutoff + timedelta(days=1), time.min)
            )
            queryset = queryset.filter(
                Q(last_contact_at__lt=cutoff)
                | (Q(last_contact_at__isnull=True) & Q(created_at__lt=created_cutoff))
            )
    except (TypeError, ValueError):
        return None, 'Informe datas no formato AAAA-MM-DD e números válidos nos filtros.'

    return queryset, None


def _apply_property_filters(queryset, arguments):
    """Filtros, preços e ordenação que só existem para imóveis."""
    if arguments.get('property_type'):
        queryset = queryset.filter(type__name__icontains=str(arguments['property_type']).strip())

    if arguments.get('neighborhood'):
        queryset = queryset.filter(neighborhood__name__icontains=str(arguments['neighborhood']).strip())

    if arguments.get('min_bedrooms') is not None:
        try:
            queryset = queryset.filter(bedrooms__gte=int(arguments['min_bedrooms']))
        except (TypeError, ValueError):
            return None, 'min_bedrooms precisa ser um número inteiro.'

    purpose = str(arguments.get('purpose') or PropertyPrice.Purpose.SALE).strip().upper()

    if purpose not in PropertyPrice.Purpose.values:
        return None, 'Finalidade inválida: use SALE, RENT ou SEASONAL.'

    order_by = arguments.get('order_by')

    if order_by and order_by not in ('price_desc', 'price_asc'):
        return None, 'Ordenação inválida: use price_desc ou price_asc.'

    queryset = queryset.annotate(
        price=_price_subquery(purpose),
        sale_price=_price_subquery(PropertyPrice.Purpose.SALE),
        rent_price=_price_subquery(PropertyPrice.Purpose.RENT),
        seasonal_price=_price_subquery(PropertyPrice.Purpose.SEASONAL),
    )

    try:
        if arguments.get('min_price') is not None:
            queryset = queryset.filter(price__gte=float(arguments['min_price']))

        if arguments.get('max_price') is not None:
            queryset = queryset.filter(price__lte=float(arguments['max_price']))
    except (TypeError, ValueError):
        return None, 'min_price e max_price precisam ser números.'

    if order_by == 'price_desc':
        queryset = queryset.order_by(F('price').desc(nulls_last=True), '-created_at')
    elif order_by == 'price_asc':
        queryset = queryset.order_by(F('price').asc(nulls_last=True), '-created_at')
    else:
        queryset = queryset.order_by('-created_at')

    return queryset, None


def _price_subquery(purpose):
    return Subquery(
        PropertyPrice.objects.filter(property=OuterRef('pk'), purpose=purpose).values('amount')[:1]
    )


def _only_overdue_tasks(queryset):
    now = timezone.localtime()
    today = now.date()

    return queryset.exclude(status=Task.Status.DONE).filter(
        Q(due_date__lt=today)
        | Q(due_date=today, due_time__isnull=False, due_time__lt=now.time())
    )


def _count_result(entity, definition, queryset, arguments):
    group_by = arguments.get('group_by')
    result = {'entity': entity, 'count': queryset.count()}

    if entity == 'deals':
        result['total_value'] = float(queryset.aggregate(total=Sum('value'))['total'] or 0)

    if entity == 'properties':
        stats = queryset.aggregate(
            with_price=Count('price'),
            price_min=Min('price'),
            price_max=Max('price'),
            price_avg=Avg('price'),
        )
        result['price_stats'] = {
            'purpose': str(arguments.get('purpose') or PropertyPrice.Purpose.SALE).upper(),
            'with_price': stats['with_price'],
            'min': float(stats['price_min'] or 0),
            'max': float(stats['price_max'] or 0),
            'avg': round(float(stats['price_avg'] or 0), 2),
        }

    if group_by:
        field = definition['group_by'].get(group_by)

        if field is None:
            return {'error': f'Agrupamento inválido para {definition["label"]}.'}

        labels = dict(definition.get('choices', {}).get(group_by, []))
        rows = queryset.values(field).annotate(count=Count('id')).order_by('-count')
        result['groups'] = [
            {
                'value': row[field],
                'label': labels.get(row[field], row[field] or 'Não informado'),
                'count': row['count'],
            }
            for row in rows
        ]

    return result


def _list_result(definition, queryset, arguments):
    try:
        limit = min(int(arguments.get('limit') or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIST_LIMIT

    fields = definition['fields']

    # Imóvel já sai ordenado (por preço ou data) e leva os preços junto; o resto sai por data.
    if arguments.get('entity') == 'properties':
        fields = fields + ('sale_price', 'rent_price', 'seasonal_price')
    else:
        queryset = queryset.order_by('-created_at')

    total = queryset.count()
    rows = list(queryset.values(*fields)[:max(limit, 1)])

    return {'count': total, 'showing': len(rows), 'results': rows}


def _dashboard_summary(user, arguments):
    if not user.can('dashboard', AccessLevel.READ):
        return {'error': 'Sem permissão para consultar o Dashboard.'}

    agency_id = user.agency_id
    now = timezone.localtime()
    today = now.date()

    properties = Property.objects.filter(agency_id=agency_id, deleted_at__isnull=True).aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(is_active=True)),
        on_site=Count('id', filter=Q(on_site=True)),
    )
    leads = Lead.objects.filter(agency_id=agency_id, deleted_at__isnull=True).aggregate(
        total=Count('id'), new=Count('id', filter=Q(status=Lead.Status.NEW))
    )
    open_deals = Deal.objects.filter(
        agency_id=agency_id, deleted_at__isnull=True, outcome__isnull=True
    ).aggregate(count=Count('id'), total_value=Sum('value'))
    pending_tasks = Task.objects.filter(agency_id=agency_id, deleted_at__isnull=True).exclude(
        status=Task.Status.DONE
    )
    open_tickets = ServiceTicket.objects.filter(
        agency_id=agency_id,
        deleted_at__isnull=True,
        status__in=[
            ServiceTicket.Status.NEW,
            ServiceTicket.Status.IN_PROGRESS,
            ServiceTicket.Status.AWAITING_RESPONSE,
        ],
    ).count()

    return {
        'properties': {
            'total': properties['total'],
            'active': properties['active'],
            'inactive': properties['total'] - properties['active'],
            'on_site': properties['on_site'],
        },
        'leads': leads,
        'open_deals': {
            'count': open_deals['count'],
            'total_value': float(open_deals['total_value'] or 0),
        },
        'tasks': {
            'today': pending_tasks.filter(due_date=today).count(),
            'overdue': _only_overdue_tasks(
                Task.objects.filter(agency_id=agency_id, deleted_at__isnull=True)
            ).count(),
        },
        'open_tickets': open_tickets,
    }


def _sales_report(user, arguments):
    if not user.can('relatorios', AccessLevel.READ):
        return {'error': 'Sem permissão para consultar Relatórios.'}

    today = timezone.localdate()

    try:
        start = date.fromisoformat(arguments['start']) if arguments.get('start') else today.replace(day=1)
        end = date.fromisoformat(arguments['end']) if arguments.get('end') else today
    except ValueError:
        return {'error': 'Informe as datas no formato AAAA-MM-DD.'}

    closed = Deal.objects.filter(
        agency_id=user.agency_id, deleted_at__isnull=True, closed_at__range=(start, end)
    ).aggregate(
        won_count=Count('id', filter=Q(outcome=Deal.Outcome.WON)),
        won_value=Sum('value', filter=Q(outcome=Deal.Outcome.WON)),
        lost_count=Count('id', filter=Q(outcome=Deal.Outcome.LOST)),
        lost_value=Sum('value', filter=Q(outcome=Deal.Outcome.LOST)),
    )

    decided = closed['won_count'] + closed['lost_count']

    return {
        'period': {'start': start.isoformat(), 'end': end.isoformat()},
        'won': {'count': closed['won_count'], 'total_value': float(closed['won_value'] or 0)},
        'lost': {'count': closed['lost_count'], 'total_value': float(closed['lost_value'] or 0)},
        'conversion_rate': round(closed['won_count'] / decided * 100, 1) if decided else 0.0,
    }


def _get_record(user, arguments):
    definition = ENTITIES.get(arguments.get('entity'))

    if definition is None:
        return {'error': 'Entidade desconhecida.'}

    if not user.can(definition['resource'], AccessLevel.READ):
        return {'error': f'Sem permissão para consultar {definition["label"]}.'}

    term = str(arguments.get('query') or '').strip()

    if not term:
        return {'error': 'Informe o código, protocolo ou nome do registro.'}

    queryset = definition['model'].objects.filter(
        agency_id=user.agency_id, deleted_at__isnull=True
    )
    matches = _find_matches(definition, queryset, term)

    if not matches:
        return {'error': 'Nenhum registro encontrado com esse código ou nome.'}

    if len(matches) > 1:
        return {
            'error': 'Mais de um registro encontrado; pergunte pelo código exato.',
            'candidates': [_identify(instance) for instance in matches[:5]],
        }

    builder = DETAIL_BUILDERS.get(arguments['entity'], _generic_detail)

    return builder(definition, matches[0])


def _find_matches(definition, queryset, term):
    key_field = definition.get('key_field')

    # O código/protocolo exato ganha da busca textual: "imóvel 14" não pode trazer o 145.
    if key_field:
        exact = list(queryset.filter(**{f'{key_field}__iexact': term})[:2])

        if exact:
            return exact

    return list(queryset.filter(_search_conditions(definition, term))[:6])


def _identify(instance):
    code = getattr(instance, 'code', None) or getattr(instance, 'protocol', None)
    name = (
        getattr(instance, 'name', None)
        or getattr(instance, 'title', None)
        or getattr(instance, 'client_name', None)
    )

    return {'code': code, 'name': name}


def _short(text, limit=600):
    return (text or '')[:limit]


def _generic_detail(definition, instance):
    # Campos de relação (com __) são de listagem via values(); aqui só os atributos diretos.
    return {
        field: getattr(instance, field)
        for field in definition['fields']
        if '__' not in field
    }


def _property_detail(definition, instance):
    return {
        'code': instance.code,
        'name': instance.name,
        'type': instance.type.name if instance.type_id else None,
        'neighborhood': instance.neighborhood.name if instance.neighborhood_id else None,
        'city': instance.neighborhood.city.name if instance.neighborhood_id else None,
        'condominium': instance.condominium.name if instance.condominium_id else None,
        'address': ' '.join(
            part for part in (instance.address, instance.number, instance.complement) if part
        ),
        'zip_code': instance.zip_code,
        'area': float(instance.area) if instance.area is not None else None,
        'built_area': float(instance.built_area) if instance.built_area is not None else None,
        'bedrooms': instance.bedrooms,
        'suites': instance.suites,
        'bathrooms': instance.bathrooms,
        'living_rooms': instance.living_rooms,
        'parking_spaces': instance.parking_spaces,
        'prices': [
            {
                'purpose': price.purpose,
                'label': price.get_purpose_display(),
                'amount': float(price.amount),
                'notes': price.notes,
            }
            for price in instance.prices.all()
        ],
        'fees': [
            {'name': property_fee.fee.name, 'amount': float(property_fee.amount)}
            for property_fee in instance.fees.select_related('fee')
        ],
        'features': [feature.name for feature in instance.features.all()],
        'broker': instance.broker.name if instance.broker_id else None,
        'owner': (instance.owner.name if instance.owner_id else None) or instance.owner_name or None,
        'flags': {
            'is_active': instance.is_active,
            'on_site': instance.on_site,
            'featured': instance.featured,
            'exclusive': instance.exclusive,
            'reserved': instance.reserved,
            'opportunity': instance.opportunity,
            'under_construction': instance.under_construction,
        },
        'description': _short(instance.description),
        'created_at': instance.created_at,
    }


def _lead_detail(definition, instance):
    return {
        'code': instance.code,
        'name': instance.name,
        'email': instance.email,
        'phone': instance.phone,
        'source': instance.get_source_display(),
        'status': instance.get_status_display(),
        'interest': instance.get_interest_display(),
        'property_type': instance.property_type,
        'budget': instance.budget,
        'city': instance.city,
        'responsible': instance.responsible.name if instance.responsible_id else None,
        'observations': _short(instance.observations),
        'last_contact_at': instance.last_contact_at,
        'created_at': instance.created_at,
        'last_interactions': [
            {'text': interaction.text, 'author': interaction.author_name, 'created_at': interaction.created_at}
            for interaction in instance.interactions.order_by('-created_at')[:5]
        ],
    }


def _service_ticket_detail(definition, instance):
    return {
        'protocol': instance.protocol,
        'client_name': instance.client_name,
        'email': instance.email,
        'phone': instance.phone,
        'subject': instance.subject,
        'category': instance.get_category_display(),
        'status': instance.get_status_display(),
        'priority': instance.get_priority_display(),
        'responsible': instance.responsible.name if instance.responsible_id else None,
        'property_code': instance.property_code,
        'description': _short(instance.description),
        'created_at': instance.created_at,
        'last_messages': [
            {
                'author': message.author_name,
                'author_type': message.get_author_type_display(),
                'message': _short(message.message, 300),
                'created_at': message.created_at,
            }
            for message in instance.messages.order_by('-created_at')[:5]
        ],
    }


def _deal_detail(definition, instance):
    return {
        'title': instance.title,
        'client_name': instance.client_name,
        'value': float(instance.value),
        'stage': instance.get_stage_display(),
        'probability': instance.probability,
        'estimated_close': instance.estimated_close,
        'responsible': instance.responsible.name if instance.responsible_id else None,
        'origin': instance.get_origin_display() if instance.origin else None,
        'type': instance.get_type_display() if instance.type else None,
        'property_code': instance.property_code,
        'outcome': instance.get_outcome_display() if instance.outcome else 'Em aberto',
        'loss_reason': instance.get_loss_reason_display() if instance.loss_reason else None,
        'closed_at': instance.closed_at,
        'lead_code': instance.lead.code if instance.lead_id else None,
        'description': _short(instance.description),
        'created_at': instance.created_at,
    }


def _task_detail(definition, instance):
    return {
        'title': instance.title,
        'type': instance.get_type_display(),
        'status': instance.get_status_display(),
        'priority': instance.get_priority_display(),
        'due_date': instance.due_date,
        'due_time': instance.due_time,
        'responsible': instance.responsible.name if instance.responsible_id else None,
        'lead_code': instance.lead.code if instance.lead_id else None,
        'deal_title': instance.deal.title if instance.deal_id else None,
        'property_code': instance.property_code,
        'description': _short(instance.description),
        'notes': _short(instance.notes, 300),
        'created_at': instance.created_at,
    }


def _client_detail(definition, instance):
    return {
        'code': instance.code,
        'name': instance.name,
        'type': instance.get_type_display(),
        'email': instance.email,
        'phone': instance.phone,
        'document': instance.document,
        'occupation': instance.occupation,
        'address': ' '.join(
            part for part in (instance.address, instance.number, instance.complement) if part
        ),
        'notes': _short(instance.notes, 300),
        'created_at': instance.created_at,
    }


def _owner_detail(definition, instance):
    return {
        'name': instance.name,
        'spouse': instance.spouse,
        'email': instance.email,
        'phone': instance.phone,
        'mobile': instance.mobile,
        'business_phone': instance.business_phone,
        'document': instance.document,
        'address': ' '.join(
            part for part in (instance.address, instance.number, instance.complement) if part
        ),
        'notes': _short(instance.notes, 300),
        'created_at': instance.created_at,
    }


def _condominium_detail(definition, instance):
    return {
        'name': instance.name,
        'address': instance.address,
        'neighborhood': instance.neighborhood.name if instance.neighborhood_id else None,
        'description': _short(instance.description),
        'features': [feature.name for feature in instance.features.all()],
        'created_at': instance.created_at,
    }


DETAIL_BUILDERS = {
    'properties': _property_detail,
    'leads': _lead_detail,
    'service_tickets': _service_ticket_detail,
    'deals': _deal_detail,
    'tasks': _task_detail,
    'clients': _client_detail,
    'owners': _owner_detail,
    'condominiums': _condominium_detail,
}

PROPERTY_SEARCH_TOOL = {
    'type': 'function',
    'function': {
        'name': 'set_property_search',
        'description': 'Converte a descrição do imóvel desejado nos filtros estruturados da busca.',
        'parameters': {
            'type': 'object',
            'properties': {
                'purpose': {
                    'type': 'string',
                    'enum': ['SALE', 'RENT', 'SEASONAL'],
                    'description': 'Comprar/venda = SALE, alugar/locação = RENT, temporada = SEASONAL.',
                },
                'property_type': {'type': 'string', 'description': 'Tipo do imóvel, ex.: Apartamento, Casa, Cobertura.'},
                'state': {'type': 'string', 'description': 'Estado citado, nome ou sigla.'},
                'city': {'type': 'string', 'description': 'Cidade citada.'},
                'neighborhood': {'type': 'string', 'description': 'Bairro ou região citada.'},
                'condominium': {'type': 'string', 'description': 'Nome do condomínio citado.'},
                'min_price': {'type': 'number', 'description': 'Preço mínimo em reais; "500 mil" = 500000.'},
                'max_price': {'type': 'number', 'description': 'Preço máximo em reais; "2 milhões" = 2000000.'},
                'min_bedrooms': {'type': 'integer', 'description': 'Número mínimo de quartos/dormitórios.'},
                'featured': {'type': 'boolean', 'description': 'true quando pedir imóveis em destaque.'},
                'exclusive': {'type': 'boolean', 'description': 'true quando pedir exclusividade.'},
                'accepts_trade': {'type': 'boolean', 'description': 'true quando pedir permuta.'},
                'has_photos': {'type': 'boolean', 'description': 'true quando pedir imóveis com foto.'},
                'in_condominium': {'type': 'boolean', 'description': 'true dentro de condomínio; false fora.'},
                'search': {
                    'type': 'string',
                    'description': (
                        'Somente características citadas no pedido que não couberam em outro '
                        'campo. Não preencha se não sobrar nada.'
                    ),
                },
            },
        },
    },
}


def extract_property_search(*, user, text):
    """Traduz a descrição em linguagem natural nos filtros da listagem de imóveis."""
    messages = [
        {
            'role': 'system',
            'content': (
                'Você converte pedidos de busca de imóveis em filtros estruturados. '
                'Preencha somente o que o texto disser explicitamente; deixe de fora todo '
                'campo não citado. Não deduza cidade ou estado a partir do bairro. '
                'Preços: "até X" vira max_price, "a partir de X" ou "acima de X" vira '
                'min_price; "500 mil" = 500000 e "2 milhões" = 2000000. '
                'Exemplos — "apartamento de 2 quartos em copacabana até 800 mil": '
                '{"property_type": "Apartamento", "min_bedrooms": 2, '
                '"neighborhood": "Copacabana", "max_price": 800000} '
                '(cidade, estado e search ficam de fora porque não foram citados); '
                '"casa com piscina em condomínio para alugar a partir de 5 mil": '
                '{"property_type": "Casa", "purpose": "RENT", "in_condominium": true, '
                '"min_price": 5000, "search": "piscina"}.'
            ),
        },
        {'role': 'user', 'content': text},
    ]

    reply = _call_grok(
        messages,
        tools=[PROPERTY_SEARCH_TOOL],
        tool_choice={'type': 'function', 'function': {'name': 'set_property_search'}},
    )
    tool_calls = reply.get('tool_calls') or []

    try:
        criteria = json.loads(tool_calls[0]['function'].get('arguments') or '{}')
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AssistantError(
            'Não foi possível interpretar a pesquisa. Tente descrever de outro jeito.'
        ) from exc

    if not isinstance(criteria, dict):
        raise AssistantError('Não foi possível interpretar a pesquisa. Tente descrever de outro jeito.')

    return _resolve_property_search(user, criteria, text)


def _brl(value):
    return f'R$ {int(value):,}'.replace(',', '.')


def _normalize(text):
    decomposed = unicodedata.normalize('NFD', str(text).lower())

    return ''.join(char for char in decomposed if not unicodedata.combining(char))


def _mentioned(term, normalized_text):
    """O modelo às vezes inventa local não citado; só passa o que aparece no pedido."""
    words = [word for word in _normalize(term).split() if len(word) >= 3]

    return any(word in normalized_text for word in words)


PRICE_AMOUNT = r'(\d[\d.,]*)(?:\s*(milhoes|milhao|mil|mi)\b)?'


def _parse_amount(number, unit):
    value = float(number.replace('.', '').replace(',', '.'))

    if unit == 'mil':
        return value * 1000

    if unit in ('milhao', 'milhoes', 'mi'):
        return value * 1000000

    return value


def _price_fallback(normalized_text):
    """O modelo às vezes perde o preço; a leitura direta de "até X"/"a partir de X" garante."""
    range_match = re.search(
        r'entre\s+(?:r\$\s*)?' + PRICE_AMOUNT + r'\s+e\s+(?:r\$\s*)?' + PRICE_AMOUNT,
        normalized_text,
    )

    if range_match:
        return (
            _parse_amount(range_match.group(1), range_match.group(2)),
            _parse_amount(range_match.group(3), range_match.group(4)),
        )

    minimum = maximum = None
    max_match = re.search(r'(?:ate|no maximo|maximo de)\s+(?:r\$\s*)?' + PRICE_AMOUNT, normalized_text)

    if max_match:
        maximum = _parse_amount(max_match.group(1), max_match.group(2))

    min_match = re.search(
        r'(?:a partir de|acima de|minimo de)\s+(?:r\$\s*)?' + PRICE_AMOUNT, normalized_text
    )

    if min_match:
        minimum = _parse_amount(min_match.group(1), min_match.group(2))

    return minimum, maximum


def _match_by_name(queryset, term, agency_condition=None):
    """Nome exato ganha do parcial; dentro do empate, prefere onde a imobiliária tem registro."""
    for lookup in ('name__iexact', 'name__icontains'):
        candidates = queryset.filter(**{lookup: term})

        if agency_condition is not None:
            match = candidates.filter(agency_condition).first()

            if match:
                return match

        match = candidates.first()

        if match:
            return match

    return None


def _resolve_property_search(user, criteria, text):
    """Casa os critérios extraídos com o catálogo real e monta os parâmetros de /properties/."""
    params = {}
    applied = []
    unmatched = []
    normalized_text = _normalize(text)

    # Local que o pedido não citou é dedução do modelo, não filtro do usuário.
    for field in ('state', 'city', 'neighborhood', 'condominium'):
        if criteria.get(field) and not _mentioned(criteria[field], normalized_text):
            criteria[field] = None

    purpose = str(criteria.get('purpose') or '').strip().upper()
    if purpose in PropertyPrice.Purpose.values:
        params['purpose'] = purpose
        applied.append(f'Objetivo: {dict(PropertyPrice.Purpose.choices)[purpose]}')

    if criteria.get('property_type'):
        term = str(criteria['property_type']).strip()
        match = _match_by_name(PropertyType.objects.filter(deleted_at__isnull=True), term)

        if match:
            params['type'] = str(match.id)
            applied.append(f'Tipo: {match.name}')
        else:
            unmatched.append(f'Tipo "{term}" não encontrado')

    state = None
    if criteria.get('state'):
        term = str(criteria['state']).strip()
        states = State.objects.filter(deleted_at__isnull=True)
        state = (
            states.filter(Q(abbreviation__iexact=term) | Q(name__iexact=term)).first()
            or states.filter(name__icontains=term).first()
        )

        if state:
            params['state'] = str(state.id)
            applied.append(f'Estado: {state.name}')
        else:
            unmatched.append(f'Estado "{term}" não encontrado')

    city = None
    if criteria.get('city'):
        term = str(criteria['city']).strip()
        cities = City.objects.filter(deleted_at__isnull=True)

        if state is not None:
            cities = cities.filter(state=state)

        # Prefere a cidade onde a imobiliária tem imóvel; nome parecido em outro estado não atrapalha.
        city = _match_by_name(
            cities,
            term,
            Q(
                neighborhoods__properties__agency_id=user.agency_id,
                neighborhoods__properties__deleted_at__isnull=True,
            ),
        )

        if city:
            params['city'] = str(city.id)
            applied.append(f'Cidade: {city.name}')
        else:
            unmatched.append(f'Cidade "{term}" não encontrada')

    if criteria.get('neighborhood'):
        term = str(criteria['neighborhood']).strip()
        neighborhoods = Neighborhood.objects.filter(deleted_at__isnull=True)

        if city is not None:
            neighborhoods = neighborhoods.filter(city=city)

        neighborhood = _match_by_name(
            neighborhoods,
            term,
            Q(properties__agency_id=user.agency_id, properties__deleted_at__isnull=True),
        )

        if neighborhood:
            params['neighborhood'] = str(neighborhood.id)
            applied.append(f'Bairro: {neighborhood.name}')
        else:
            unmatched.append(f'Bairro "{term}" não encontrado')

    if criteria.get('condominium'):
        term = str(criteria['condominium']).strip()
        condominium = _match_by_name(
            Condominium.objects.filter(agency_id=user.agency_id, deleted_at__isnull=True), term
        )

        if condominium:
            params['condominium'] = str(condominium.id)
            applied.append(f'Condomínio: {condominium.name}')
        else:
            unmatched.append(f'Condomínio "{term}" não encontrado')

    try:
        if criteria.get('min_price') is not None:
            params['price_min'] = float(criteria['min_price'])

        if criteria.get('max_price') is not None:
            params['price_max'] = float(criteria['max_price'])

        if criteria.get('min_bedrooms') is not None:
            params['bedrooms_min'] = int(criteria['min_bedrooms'])
            applied.append(f'{params["bedrooms_min"]}+ quartos')
    except (TypeError, ValueError):
        unmatched.append('Valores numéricos não reconhecidos')

    fallback_min, fallback_max = _price_fallback(normalized_text)

    if 'price_min' not in params and fallback_min is not None:
        params['price_min'] = fallback_min

    if 'price_max' not in params and fallback_max is not None:
        params['price_max'] = fallback_max

    if 'price_min' in params:
        applied.append(f'Preço mín: {_brl(params["price_min"])}')

    if 'price_max' in params:
        applied.append(f'Preço máx: {_brl(params["price_max"])}')

    # Flag só vale com a palavra correspondente no pedido; sem ela é invenção do modelo.
    for flag, label, keywords in (
        ('featured', 'Destaque', ('destaque', 'destacad')),
        ('exclusive', 'Exclusividade', ('exclusiv',)),
        ('accepts_trade', 'Aceita permuta', ('permuta',)),
        ('has_photos', 'Com foto', ('foto',)),
    ):
        if criteria.get(flag) is True and any(keyword in normalized_text for keyword in keywords):
            params[flag] = True
            applied.append(label)

    if isinstance(criteria.get('in_condominium'), bool) and 'condominio' in normalized_text:
        params['has_condominium'] = criteria['in_condominium']
        applied.append('Em condomínio' if criteria['in_condominium'] else 'Fora de condomínio')

    if criteria.get('search'):
        term = str(criteria['search']).strip()

        # Sobra curta e sem números é busca útil; pedido inteiro ou lixo numérico zeraria o resultado.
        acceptable = (
            term
            and not any(char.isdigit() for char in term)
            and _normalize(term) != normalized_text
            and len(term) <= max(40, len(text) // 2)
        )
        if acceptable:
            params['search'] = term
            applied.append(f'Busca: {term}')

    return {'params': params, 'applied': applied, 'unmatched': unmatched}


TOOL_HANDLERS = {
    'query_records': _query_records,
    'get_record': _get_record,
    'dashboard_summary': _dashboard_summary,
    'sales_report': _sales_report,
}
