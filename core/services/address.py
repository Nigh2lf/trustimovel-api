import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from django.db import transaction

from core.models import City, Country, Neighborhood, State

VIACEP_URL = 'https://viacep.com.br/ws/{zip_code}/json/'
VIACEP_TIMEOUT = 10


class AddressLookupError(Exception):
    """CEP inválido, inexistente ou serviço indisponível."""


def find_or_create_address(*, zip_code: str) -> dict:
    """Casa o CEP do ViaCEP com o catálogo local, criando estado, cidade ou bairro que faltar."""
    digits = normalize_zip_code(zip_code)
    payload = _fetch_viacep(digits)

    return _sync_catalog(digits, payload)


def normalize_zip_code(zip_code: str) -> str:
    digits = ''.join(character for character in str(zip_code) if character.isdigit())

    if len(digits) != 8:
        raise AddressLookupError('Informe um CEP com 8 dígitos.')

    return digits


def _fetch_viacep(digits: str) -> dict:
    # A chamada externa fica fora da transação para não segurar conexão do banco.
    try:
        with urlopen(VIACEP_URL.format(zip_code=digits), timeout=VIACEP_TIMEOUT) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AddressLookupError('Não foi possível consultar o CEP agora. Tente novamente.') from exc

    if payload.get('erro') in (True, 'true'):
        raise AddressLookupError('CEP não encontrado.')

    if not payload.get('uf') or not payload.get('localidade'):
        raise AddressLookupError('CEP não encontrado.')

    return payload


@transaction.atomic
def _sync_catalog(digits: str, payload: dict) -> dict:
    country, _created = Country.objects.get_or_create(code='BRA', defaults={'name': 'Brasil'})

    abbreviation = payload['uf'].strip().upper()
    state, _created = State.objects.get_or_create(
        country=country,
        abbreviation=abbreviation,
        defaults={'name': payload.get('estado') or abbreviation},
    )

    city = _find_or_create_city(state, payload)
    neighborhood = _find_or_create_neighborhood(city, payload.get('bairro'))

    return {
        'zip_code': f'{digits[:5]}-{digits[5:]}',
        'address': (payload.get('logradouro') or '').strip(),
        'complement': (payload.get('complemento') or '').strip(),
        'country': {'id': country.id, 'name': country.name},
        'state': {'id': state.id, 'name': state.name, 'abbreviation': state.abbreviation},
        'city': {'id': city.id, 'name': city.name},
        'neighborhood': (
            {'id': neighborhood.id, 'name': neighborhood.name} if neighborhood else None
        ),
    }


def _find_or_create_city(state: State, payload: dict) -> City:
    name = payload['localidade'].strip()
    ibge_code = (payload.get('ibge') or '').strip()

    # O código IBGE é único no catálogo, então ele manda quando o ViaCEP o informa.
    if ibge_code:
        city, _created = City.objects.get_or_create(
            ibge_code=ibge_code,
            defaults={'state': state, 'name': name},
        )

        return city

    city = City.objects.filter(state=state, name__iexact=name).first()

    if city is None:
        raise AddressLookupError('Cidade do CEP não encontrada no cadastro.')

    return city


def _find_or_create_neighborhood(city: City, name) -> Neighborhood | None:
    # CEP único de cidade pequena volta sem bairro; nesse caso quem escolhe é o usuário.
    name = (name or '').strip()

    if not name:
        return None

    neighborhood = Neighborhood.objects.filter(city=city, name__iexact=name).first()

    if neighborhood is not None:
        return neighborhood

    return Neighborhood.objects.create(city=city, name=name)
