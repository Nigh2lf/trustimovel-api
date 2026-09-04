"""Fila de atendimento (roleta de leads): quem é a vez, os prazos e cada transição.

O lead entra, a fila escolhe o corretor da vez e ele tem um prazo curto para aceitar; não
aceitou, o lead passa ao próximo. Depois do aceite corre o SLA de primeira resposta. Cada
passo vira uma `LeadInteraction`, que é a linha do tempo que explica por que o lead foi
para quem foi. O estado vive no próprio `Lead` e no `User` do corretor, sem tabela própria.
"""

import random
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from core.models import AgencySettings, Lead, LeadInteraction, User

QueueStatus = Lead.QueueStatus
EventType = LeadInteraction.Type

ACTIVE_STATUSES = [QueueStatus.OFFERED, QueueStatus.ACCEPTED, QueueStatus.IN_SERVICE]
OPEN_STATUSES = [QueueStatus.WAITING, *ACTIVE_STATUSES]

# Quem recusou, deixou expirar, estourou o SLA ou devolveu não recebe o mesmo lead de novo.
ATTEMPT_EVENTS = [EventType.DECLINED, EventType.EXPIRED, EventType.SLA_BREACH, EventType.RETURNED]

REASON_ROTATION = 'Rodízio'
REASON_RETURNING = 'Regra de retorno'
REASON_LOAD = 'Menor carga'
REASON_RANDOM = 'Sorteio'
REASON_MANAGER = 'Escolha do gestor'


class QueueError(Exception):
    """Ação inválida para o estado atual; a mensagem é mostrada a quem usa o sistema."""


def settings_for(agency_id):
    settings, _ = AgencySettings.objects.get_or_create(agency_id=agency_id)
    return settings


def brokers_for(agency_id):
    """Corretores da imobiliária na ordem da roleta, inclusive os que estão fora dela."""
    return list(
        User.objects.filter(
            agency_id=agency_id,
            type=User.Type.BROKER,
            is_active=True,
            deleted_at__isnull=True,
        ).order_by('queue_order', 'name', 'email')
    )


def queue_leads(agency_id):
    return Lead.objects.filter(agency_id=agency_id, deleted_at__isnull=True)


def display_name(user):
    return user.name or user.email


def attempted_user_ids(lead):
    return set(
        lead.interactions.filter(type__in=ATTEMPT_EVENTS, user__isnull=False).values_list(
            'user_id', flat=True
        )
    )


def active_loads(agency_id):
    """{id do corretor: atendimentos em mãos}, numa consulta só."""
    rows = (
        queue_leads(agency_id)
        .filter(queue_status__in=ACTIVE_STATUSES, assigned_to__isnull=False)
        .values('assigned_to_id')
        .annotate(total=Count('id'))
    )
    return {row['assigned_to_id']: row['total'] for row in rows}


def is_within_business_hours(settings, now):
    local = timezone.localtime(now)
    # O painel conta os dias com 0 = domingo; o weekday() do Python começa na segunda.
    weekday = (local.weekday() + 1) % 7

    if weekday not in (settings.queue_business_days or []):
        return False

    return settings.queue_business_start <= local.time() < settings.queue_business_end


def eligible_brokers(settings, brokers, attempts, loads):
    limit = settings.queue_max_active_per_broker

    return [
        broker
        for broker in brokers
        if broker.in_queue
        and broker.queue_presence == User.QueuePresence.AVAILABLE
        and broker.id not in attempts
        and (not limit or loads.get(broker.id, 0) < limit)
    ]


def blocking_reason(brokers, attempts):
    """Por que ninguém é elegível, para a tela explicar a espera em vez de só mostrar "aguardando"."""
    in_queue = [broker for broker in brokers if broker.in_queue]
    if not in_queue:
        return 'Nenhum corretor participa da roleta'

    available = [b for b in in_queue if b.queue_presence == User.QueuePresence.AVAILABLE]
    if not available:
        return 'Todos os corretores estão pausados ou fora da fila'

    fresh = [broker for broker in available if broker.id not in attempts]
    if not fresh:
        return 'Todos os disponíveis já passaram por este lead'

    return 'Todos os disponíveis estão no limite de atendimentos simultâneos'


def returning_broker(settings, lead, brokers, attempts, now):
    """Cliente que já falou com um corretor na janela configurada volta para ele, furando o rodízio."""
    days = settings.queue_return_window_days
    if not days:
        return None

    identity = Q()
    if lead.phone:
        identity |= Q(phone=lead.phone)
    if lead.email:
        identity |= Q(email__iexact=lead.email)
    if not identity:
        return None

    since = now - timedelta(days=days)
    previous = (
        queue_leads(lead.agency_id)
        .filter(identity, assigned_to__isnull=False)
        .filter(Q(accepted_at__gte=since) | Q(accepted_at__isnull=True, created_at__gte=since))
        .exclude(pk=lead.pk)
        .order_by('-accepted_at', '-created_at')
        .first()
    )
    if previous is None:
        return None

    broker = next((b for b in brokers if b.id == previous.assigned_to_id), None)
    if broker is None or not broker.in_queue:
        return None
    if broker.queue_presence != User.QueuePresence.AVAILABLE or broker.id in attempts:
        return None

    return broker


def pick_broker(settings, brokers, candidates, loads):
    """Escolhe o próximo da vez segundo o modo em vigor. Devolve (corretor, motivo)."""
    if not candidates:
        return None, ''

    mode = settings.queue_mode

    if mode == AgencySettings.QueueMode.LOAD:
        broker = min(candidates, key=lambda b: (loads.get(b.id, 0), b.queue_order))
        return broker, REASON_LOAD

    if mode == AgencySettings.QueueMode.RANDOM:
        return random.choice(candidates), REASON_RANDOM

    # Sequencial: a lista já está na ordem da vez, e quem recebe vai para o final.
    ids = {broker.id for broker in candidates}
    broker = next((b for b in brokers if b.in_queue and b.id in ids), None)
    return broker, REASON_ROTATION


def _renumber(brokers):
    for position, broker in enumerate(brokers):
        broker.queue_order = position
    User.objects.bulk_update(brokers, ['queue_order'])


def send_to_end(brokers, broker):
    _renumber([b for b in brokers if b.id != broker.id] + [broker])


def send_to_front(brokers, broker):
    _renumber([broker] + [b for b in brokers if b.id != broker.id])


def _hold(lead, detail):
    lead.queue_status = QueueStatus.WAITING
    lead.assigned_to = None
    lead.deadline_at = None
    return [(EventType.HELD, None, detail)]


def dispatch(settings, lead, now, extra_attempts=()):
    """Acha o próximo da vez e oferta, mexendo no lead em memória.

    Devolve os eventos a gravar; quem chama decide se persiste, para o relógio poder
    tentar de novo um lead na espera sem encher a linha do tempo de repetições.
    """
    if settings.queue_off_hours == AgencySettings.QueueOffHours.HOLD and not is_within_business_hours(
        settings, now
    ):
        return _hold(lead, 'Fora do expediente: retido para o próximo turno')

    if settings.queue_mode == AgencySettings.QueueMode.MANUAL:
        return _hold(lead, 'Distribuição manual: aguardando o gestor')

    brokers = brokers_for(lead.agency_id)
    attempts = attempted_user_ids(lead) | set(extra_attempts)
    loads = active_loads(lead.agency_id)

    returning = returning_broker(settings, lead, brokers, attempts, now)
    if returning is not None:
        broker, reason = returning, REASON_RETURNING
    else:
        broker, reason = pick_broker(settings, brokers, eligible_brokers(settings, brokers, attempts, loads), loads)

    if broker is None:
        return _hold(lead, blocking_reason(brokers, attempts))

    # Quem recebe pela fila vai para o final dela; retorno de cliente não consome a vez.
    if returning is None:
        send_to_end(brokers, broker)

    lead.assigned_to = broker
    lead.queue_reason = reason
    lead.offered_at = now
    lead.sla_breached = False
    events = [(EventType.OFFERED, broker, f'{display_name(broker)} · {reason}')]

    if settings.queue_auto_assign:
        lead.queue_status = QueueStatus.ACCEPTED
        lead.accepted_at = now
        lead.deadline_at = now + timedelta(minutes=settings.queue_first_response_minutes)
        events.append((EventType.ACCEPTED, broker, 'Atribuição automática, sem etapa de aceite'))
        return events

    lead.queue_status = QueueStatus.OFFERED
    lead.accepted_at = None
    lead.deadline_at = now + timedelta(minutes=settings.queue_accept_minutes)
    return events


def apply_skip(settings, broker, now):
    """Corretor que deixa a oferta estourar vezes seguidas sai da roleta sozinho."""
    limit = settings.queue_skips_before_pause
    broker.queue_skips += 1

    if limit and broker.queue_skips >= limit:
        clock = timezone.localtime(now).strftime('%H:%M')
        broker.queue_presence = User.QueuePresence.PAUSED
        broker.queue_pause_reason = f'Pausado automaticamente às {clock} por perder {limit} ofertas seguidas'
        broker.queue_skips = 0

    broker.save(update_fields=['queue_skips', 'queue_presence', 'queue_pause_reason', 'updated_at'])


def pass_along(settings, lead, broker, event_type, detail, now):
    """Tira o lead das mãos do corretor e procura o próximo."""
    lead.queue_status = QueueStatus.WAITING
    lead.assigned_to = None
    lead.deadline_at = None
    events = [(event_type, broker, f'{display_name(broker)} · {detail}')]

    # Só deixar o prazo estourar pesa na auto-pausa: punir a recusa com motivo ensinaria a estourar calado.
    if event_type in (EventType.EXPIRED, EventType.SLA_BREACH):
        apply_skip(settings, broker, now)

    events += dispatch(settings, lead, now, extra_attempts=[broker.id])

    # "Manter a posição": a recusa não consome a vez, então quem recusou volta ao começo da fila.
    keep = settings.queue_decline_behavior == AgencySettings.QueueDeclineBehavior.KEEP
    if event_type == EventType.DECLINED and keep:
        send_to_front(brokers_for(lead.agency_id), broker)

    return events


def _persist(lead, events, now):
    lead.save()

    # Carimbos crescentes: eventos da mesma rodada precisam manter a ordem na linha do tempo.
    for position, (event_type, user, detail) in enumerate(events):
        LeadInteraction.objects.create(
            lead=lead,
            type=event_type,
            user=user,
            author_name=display_name(user) if user else '',
            text=detail,
            created_at=now + timedelta(microseconds=position),
        )


def _locked(lead):
    return Lead.objects.select_for_update().get(pk=lead.pk)


@transaction.atomic
def enqueue(lead, now=None):
    now = now or timezone.now()
    lead = _locked(lead)

    if lead.queue_status in OPEN_STATUSES:
        raise QueueError('Este lead já está na fila.')

    settings = settings_for(lead.agency_id)
    lead.queue_reason = ''
    lead.offered_at = None
    lead.accepted_at = None
    lead.contacted_at = None
    lead.queue_closed_at = None
    lead.sla_breached = False

    events = [(EventType.ENQUEUED, None, f'Origem: {lead.get_source_display()}')]
    events += dispatch(settings, lead, now)
    _persist(lead, events, now)
    return lead


@transaction.atomic
def accept(lead, now=None):
    now = now or timezone.now()
    lead = _locked(lead)

    if lead.queue_status != QueueStatus.OFFERED or lead.assigned_to_id is None:
        raise QueueError('Este lead não está aguardando aceite.')

    settings = settings_for(lead.agency_id)
    broker = lead.assigned_to
    lead.queue_status = QueueStatus.ACCEPTED
    lead.accepted_at = now
    lead.deadline_at = now + timedelta(minutes=settings.queue_first_response_minutes)
    _persist(lead, [(EventType.ACCEPTED, broker, f'{display_name(broker)} aceitou')], now)

    broker.queue_skips = 0
    broker.save(update_fields=['queue_skips', 'updated_at'])
    return lead


@transaction.atomic
def decline(lead, reason, now=None):
    now = now or timezone.now()
    lead = _locked(lead)

    if lead.queue_status != QueueStatus.OFFERED or lead.assigned_to_id is None:
        raise QueueError('Este lead não está aguardando aceite.')

    settings = settings_for(lead.agency_id)
    events = pass_along(
        settings, lead, lead.assigned_to, EventType.DECLINED, reason or 'Sem motivo informado', now
    )
    _persist(lead, events, now)
    return lead


@transaction.atomic
def add_note(lead, user, text, now=None):
    """Registra o que foi feito com o cliente; a primeira ação depois do aceite é o 1º contato."""
    now = now or timezone.now()
    lead = _locked(lead)
    lead.last_contact_at = timezone.localdate(now)

    if lead.queue_status != QueueStatus.ACCEPTED:
        _persist(lead, [(EventType.NOTE, user, text)], now)
        return lead.interactions.latest('created_at')

    late = lead.deadline_at is not None and now > lead.deadline_at
    lead.queue_status = QueueStatus.IN_SERVICE
    lead.contacted_at = now
    lead.deadline_at = None
    lead.sla_breached = lead.sla_breached or late

    if lead.status == Lead.Status.NEW:
        lead.status = Lead.Status.IN_CONTACT

    detail = f'{text} · registrado fora do prazo' if late else text
    _persist(lead, [(EventType.FIRST_CONTACT, user, detail)], now)
    return lead.interactions.latest('created_at')


@transaction.atomic
def close(lead, outcome, detail, now=None):
    now = now or timezone.now()
    lead = _locked(lead)

    if lead.queue_status not in OPEN_STATUSES:
        raise QueueError('Este lead não está em atendimento na fila.')

    won = outcome == 'WON'
    lead.queue_status = QueueStatus.CLOSED
    lead.queue_closed_at = now
    lead.deadline_at = None

    # Convertido em negócio é o passo seguinte, feito no CRM; aqui o atendimento só qualifica ou descarta.
    if won and lead.status != Lead.Status.CONVERTED:
        lead.status = Lead.Status.QUALIFIED
    if not won:
        lead.status = Lead.Status.UNQUALIFIED

    label = 'Qualificado' if won else 'Perdido'
    _persist(lead, [(EventType.CLOSED, lead.assigned_to, f'{label} · {detail}' if detail else label)], now)
    return lead


@transaction.atomic
def return_to_queue(lead, reason, now=None):
    """Gestor puxa o lead de volta para a fila: o corretor sumiu ou o cliente reclamou."""
    now = now or timezone.now()
    lead = _locked(lead)

    if lead.queue_status not in ACTIVE_STATUSES or lead.assigned_to_id is None:
        raise QueueError('Este lead não está com nenhum corretor.')

    settings = settings_for(lead.agency_id)
    events = pass_along(
        settings, lead, lead.assigned_to, EventType.RETURNED, reason or 'Devolvido pelo gestor', now
    )
    _persist(lead, events, now)
    return lead


@transaction.atomic
def assign(lead, broker, now=None):
    """Atribuição manual: escapa da roleta, mas fica registrada como tal."""
    now = now or timezone.now()
    lead = _locked(lead)

    if lead.queue_status not in OPEN_STATUSES:
        raise QueueError('Este lead não está na fila.')

    settings = settings_for(lead.agency_id)
    lead.assigned_to = broker
    lead.queue_reason = REASON_MANAGER
    lead.offered_at = now
    lead.contacted_at = None
    lead.sla_breached = False
    events = [(EventType.ASSIGNED, broker, display_name(broker))]

    if settings.queue_auto_assign:
        lead.queue_status = QueueStatus.ACCEPTED
        lead.accepted_at = now
        lead.deadline_at = now + timedelta(minutes=settings.queue_first_response_minutes)
        events.append((EventType.ACCEPTED, broker, 'Atribuição automática, sem etapa de aceite'))
    else:
        lead.queue_status = QueueStatus.OFFERED
        lead.accepted_at = None
        lead.deadline_at = now + timedelta(minutes=settings.queue_accept_minutes)

    _persist(lead, events, now)
    return lead


def set_presence(broker, presence, pause_reason=''):
    broker.queue_presence = presence
    broker.queue_pause_reason = pause_reason if presence == User.QueuePresence.PAUSED else ''
    broker.queue_skips = 0
    broker.save(update_fields=['queue_presence', 'queue_pause_reason', 'queue_skips', 'updated_at'])
    return broker


def toggle_queue(broker):
    broker.in_queue = not broker.in_queue
    broker.save(update_fields=['in_queue', 'updated_at'])
    return broker


@transaction.atomic
def move_broker(broker, direction):
    """Sobe (-1) ou desce (+1) o corretor na roleta; a ordem é renumerada sem buracos."""
    brokers = brokers_for(broker.agency_id)
    index = next((i for i, b in enumerate(brokers) if b.id == broker.id), -1)
    target = index + direction

    if index < 0 or target < 0 or target >= len(brokers):
        return

    brokers[index], brokers[target] = brokers[target], brokers[index]
    _renumber(brokers)


@transaction.atomic
def tick(agency_id, now=None):
    """Passa o relógio: expira ofertas, transfere quem estourou o SLA e tenta de novo a espera.

    Roda a cada leitura da fila e no comando `queuetick`; é idempotente, pode repetir à vontade.
    """
    now = now or timezone.now()
    settings = settings_for(agency_id)
    leads = queue_leads(agency_id).select_for_update()

    expired = leads.filter(queue_status=QueueStatus.OFFERED, deadline_at__lt=now).order_by('deadline_at')
    for lead in expired:
        events = pass_along(
            settings,
            lead,
            lead.assigned_to,
            EventType.EXPIRED,
            f'Não aceitou em {settings.queue_accept_minutes} min',
            now,
        )
        _persist(lead, events, now)

    # Aceitou e não fez o primeiro contato no prazo: o lead vai para o próximo, como na oferta ignorada.
    breached = leads.filter(queue_status=QueueStatus.ACCEPTED, deadline_at__lt=now).order_by('deadline_at')
    for lead in breached:
        events = pass_along(
            settings,
            lead,
            lead.assigned_to,
            EventType.SLA_BREACH,
            f'Sem primeiro contato em {settings.queue_first_response_minutes} min',
            now,
        )
        # O atraso fica no lead mesmo depois de trocar de corretor: o cliente esperou.
        lead.sla_breached = True
        _persist(lead, events, now)

    # Quem ficou na espera tenta de novo: alguém pode ter voltado da pausa desde a última rodada.
    for lead in leads.filter(queue_status=QueueStatus.WAITING).order_by('created_at'):
        events = dispatch(settings, lead, now)
        if lead.queue_status != QueueStatus.WAITING:
            _persist(lead, events, now)
