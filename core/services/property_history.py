"""Registro do histórico de alterações do imóvel.

O diff é montado sobre um retrato do imóvel (`snapshot`) tirado antes e depois de salvar,
já com os valores prontos para leitura — o histórico é para o corretor, não para o log.
"""

from core.models import PropertyHistory

TRACKED_FIELDS = {
    'code': 'Código',
    'name': 'Nome',
    'type': 'Tipo',
    'condominium': 'Condomínio',
    'neighborhood': 'Bairro',
    'broker': 'Captador',
    'owner': 'Proprietário',
    'owner_name': 'Nome do proprietário',
    'local_contact': 'Contato no local',
    'contact_phone': 'Telefone de contato',
    'description': 'Descrição',
    'address': 'Endereço',
    'number': 'Número',
    'complement': 'Complemento',
    'zip_code': 'CEP',
    'region': 'Região',
    'area': 'Área total',
    'built_area': 'Área construída',
    'bedrooms': 'Quartos',
    'suites': 'Suítes',
    'bathrooms': 'Banheiros',
    'living_rooms': 'Salas',
    'parking_spaces': 'Vagas',
    'guests': 'Hóspedes',
    'video_url': 'Vídeo',
    'maps_url': 'Mapa',
    'visit_notes': 'Observações de visita',
    'document_notes': 'Observações da documentação',
    'trade_conditions': 'Condições de permuta',
    'is_active': 'Ativo',
    'featured': 'Destaque',
    'exclusive': 'Exclusivo',
    'reserved': 'Reservado',
    'under_construction': 'Em construção',
    'opportunity': 'Oportunidade',
    'has_leasehold': 'Laudêmio',
    'on_site': 'Publicado no site',
    'show_prices': 'Mostrar valores',
    'accepts_trade': 'Aceita permuta',
}


def author_name(user):
    if user is None or not getattr(user, 'is_authenticated', False):
        return ''

    return user.name or user.email


def snapshot(instance):
    """Retrato do imóvel com os valores já legíveis, indexado pelo rótulo da tela."""
    data = {label: _display(instance, field) for field, label in TRACKED_FIELDS.items()}

    for price in instance.prices.all():
        data[f'Valor de {price.get_purpose_display()}'] = _number(price.amount)

    for fee in instance.fees.all():
        data[f'Taxa de {fee.fee.name}'] = _number(fee.amount)

    return data


def diff(before, after):
    changes = [
        {'label': label, 'from': before.get(label, ''), 'to': value}
        for label, value in after.items()
        if before.get(label, '') != value
    ]
    # Valor ou taxa que saiu do imóvel não aparece no retrato novo, só no antigo.
    changes += [
        {'label': label, 'from': value, 'to': ''}
        for label, value in before.items()
        if label not in after
    ]

    return sorted(changes, key=lambda change: change['label'])


def record(instance, user, action, notes='', changes=None):
    return PropertyHistory.objects.create(
        property=instance,
        user=user if user is not None and user.is_authenticated else None,
        author_name=author_name(user),
        action=action,
        notes=notes,
        changes=changes or [],
    )


def record_update(instance, user, before):
    """Alteração sem diferença nenhuma não vira linha no histórico."""
    changes = diff(before, snapshot(instance))

    if not changes:
        return None

    return record(instance, user, PropertyHistory.Action.UPDATED, changes=changes)


def _display(instance, field):
    value = getattr(instance, field, None)

    if value is None:
        return ''

    if isinstance(value, bool):
        return 'Sim' if value else 'Não'

    # Relação vira o nome que a tela mostra; o UUID não diria nada a quem lê.
    return getattr(value, 'name', None) or str(value)


def _number(value):
    return f'{value:.2f}' if value is not None else ''
