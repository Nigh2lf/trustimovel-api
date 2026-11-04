"""Feed XML dos imóveis para os portais, no formato VRSync (ZAP, Viva Real, OLX e afins).

Cada portal ativado pela imobiliária ganha duas URLs públicas: uma só com os imóveis marcados
para ele e outra com todos os imóveis ativos. A chave na URL é derivada da SECRET_KEY, então
não há campo novo no banco e o endereço não é adivinhável a partir do nome da imobiliária.
"""

import re
import unicodedata
from xml.etree import ElementTree

from django.db.models import Prefetch
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from core.models import Feature, Property, PropertyFee, PropertyPhoto, PropertyPrice

FEED_KEY_SALT = 'core.services.property_feed'

VRSYNC_NAMESPACE = 'http://www.vivareal.com/schemas/1.0/VRSync'

# Palavras do nome do tipo cadastrado e a categoria correspondente do VRSync; a ordem importa.
PROPERTY_TYPE_KEYWORDS = (
    (('casa de condominio', 'casa em condominio'), 'Residential / Condo'),
    (('cobertura',), 'Residential / Penthouse'),
    (('apartamento', 'flat', 'kitnet', 'loft', 'studio'), 'Residential / Apartment'),
    (('terreno', 'lote', 'area'), 'Residential / Land Lot'),
    (('sitio', 'chacara', 'fazenda', 'haras'), 'Residential / Farm Ranch'),
    (('sala', 'escritorio', 'conjunto', 'consultorio'), 'Commercial / Office'),
    (('loja', 'ponto'), 'Commercial / Business'),
    (('galpao', 'deposito', 'armazem', 'industrial'), 'Commercial / Industrial'),
    (('predio', 'edificio'), 'Commercial / Building'),
    (('hotel', 'pousada'), 'Commercial / Hotel'),
    (('casa', 'sobrado', 'casarao', 'chale', 'bangalo'), 'Residential / Home'),
)

CONDOMINIUM_FEE_NAME = 'condominio'
PROPERTY_TAX_FEE_NAME = 'iptu'


def feed_key(agency) -> str:
    """Chave estável da imobiliária na URL do feed, sem gravar nada no banco."""
    return salted_hmac(FEED_KEY_SALT, str(agency.id)).hexdigest()[:24]


def is_valid_feed_key(agency, key) -> bool:
    return constant_time_compare(feed_key(agency), key or '')


def feed_properties(*, agency, exporter, include_all):
    """Imóveis ativos da imobiliária; sem `include_all`, só os marcados para o portal."""
    properties = (
        Property.objects.filter(agency=agency, deleted_at__isnull=True, is_active=True)
        .select_related('type', 'neighborhood__city__state')
        .prefetch_related(
            Prefetch(
                'photos',
                queryset=PropertyPhoto.objects.filter(deleted_at__isnull=True).order_by(
                    '-is_main', 'position', 'created_at'
                ),
            ),
            'prices',
            Prefetch('fees', queryset=PropertyFee.objects.select_related('fee')),
            Prefetch('features', queryset=Feature.objects.filter(deleted_at__isnull=True)),
        )
        .order_by('code')
    )

    if not include_all:
        properties = properties.filter(exporters__exporter=exporter)

    return properties


def build_feed(*, agency, properties, request) -> bytes:
    root = ElementTree.Element(
        'ListingDataFeed',
        {
            'xmlns': VRSYNC_NAMESPACE,
            'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            'xsi:schemaLocation': f'{VRSYNC_NAMESPACE} http://xml.vivareal.com/vrsync.xsd',
        },
    )

    header = ElementTree.SubElement(root, 'Header')
    _text(header, 'Provider', agency.name)
    _text(header, 'Email', agency.email)
    _text(header, 'ContactName', agency.name)
    _text(header, 'PublishDate', _timestamp(timezone.now()))
    _text(header, 'Telephone', agency.phone)

    listings = ElementTree.SubElement(root, 'Listings')

    for property in properties:
        _append_listing(listings, property, agency, request)

    return ElementTree.tostring(root, encoding='utf-8', xml_declaration=True)


def _append_listing(parent, property, agency, request):
    listing = ElementTree.SubElement(parent, 'Listing')
    prices = {price.purpose: price for price in property.prices.all() if price.show_price}

    _text(listing, 'ListingID', property.code)
    _text(listing, 'Title', property.name)
    _text(listing, 'TransactionType', _transaction_type(prices))
    _text(listing, 'Featured', 'true' if property.featured else 'false')
    _text(listing, 'ListDate', _timestamp(property.created_at))
    _text(listing, 'LastUpdateDate', _timestamp(property.updated_at))

    media = ElementTree.SubElement(listing, 'Media')

    for photo in property.photos.all():
        item = ElementTree.SubElement(
            media, 'Item', {'medium': 'image', 'primary': 'true' if photo.is_main else 'false'}
        )
        # Com S3 a URL já vem absoluta; em disco local ela é relativa e ganha o domínio da API.
        item.text = request.build_absolute_uri(photo.image.url)

    if property.video_url:
        ElementTree.SubElement(media, 'Item', {'medium': 'video'}).text = property.video_url

    details = ElementTree.SubElement(listing, 'Details')
    _text(details, 'PropertyType', _property_type(property.type))
    _text(details, 'Description', property.description)

    sale = prices.get(PropertyPrice.Purpose.SALE)
    rent = prices.get(PropertyPrice.Purpose.RENT) or prices.get(PropertyPrice.Purpose.SEASONAL)

    if sale:
        _text(details, 'ListPrice', _amount(sale.amount), {'currency': 'BRL'})

    if rent:
        period = 'Monthly' if rent.purpose == PropertyPrice.Purpose.RENT else 'Daily'
        _text(details, 'RentalPrice', _amount(rent.amount), {'currency': 'BRL', 'period': period})

    for property_fee in property.fees.all():
        fee_name = _normalize(property_fee.fee.name)

        if fee_name == CONDOMINIUM_FEE_NAME:
            _text(details, 'PropertyAdministrationFee', _amount(property_fee.amount), {'currency': 'BRL'})
        elif fee_name == PROPERTY_TAX_FEE_NAME:
            _text(details, 'YearlyTax', _amount(property_fee.amount), {'currency': 'BRL'})

    living_area = property.built_area or property.area

    if living_area:
        _text(details, 'LivingArea', _amount(living_area), {'unit': 'square metres'})

    if property.built_area and property.area:
        _text(details, 'LotArea', _amount(property.area), {'unit': 'square metres'})

    _text(details, 'Bedrooms', str(property.bedrooms))
    _text(details, 'Bathrooms', str(property.bathrooms))
    _text(details, 'Suites', str(property.suites))
    _text(details, 'Garage', str(property.parking_spaces), {'type': 'Parking Lot'})

    features = list(property.features.all())

    if features:
        features_element = ElementTree.SubElement(details, 'Features')

        for feature in features:
            _text(features_element, 'Feature', feature.name)

    location = ElementTree.SubElement(listing, 'Location', {'displayAddress': 'Neighborhood'})
    _text(location, 'Country', 'Brasil', {'abbreviation': 'BR'})

    neighborhood = property.neighborhood

    if neighborhood:
        state = neighborhood.city.state
        _text(location, 'State', state.name, {'abbreviation': state.abbreviation})
        _text(location, 'City', neighborhood.city.name)
        _text(location, 'Neighborhood', neighborhood.name)

    _text(location, 'Address', property.address)
    _text(location, 'StreetNumber', property.number)
    _text(location, 'Complement', property.complement)
    _text(location, 'PostalCode', property.zip_code)

    contact = ElementTree.SubElement(listing, 'ContactInfo')
    _text(contact, 'Name', agency.name)
    _text(contact, 'Email', agency.email)
    _text(contact, 'Website', agency.site)
    _text(contact, 'Telephone', agency.phone)


def _text(parent, tag, value, attributes=None):
    # Campo vazio fica de fora: o portal prefere a ausência da tag a uma tag em branco.
    if value in (None, ''):
        return None

    element = ElementTree.SubElement(parent, tag, attributes or {})
    element.text = str(value)

    return element


def _timestamp(value):
    return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M:%S')


def _amount(value):
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def _transaction_type(prices):
    has_sale = PropertyPrice.Purpose.SALE in prices
    has_rent = PropertyPrice.Purpose.RENT in prices or PropertyPrice.Purpose.SEASONAL in prices

    if has_sale and has_rent:
        return 'Sale/Rent'

    if has_rent:
        return 'For Rent'

    return 'For Sale'


def _normalize(text):
    decomposed = unicodedata.normalize('NFD', str(text).lower())

    return ''.join(char for char in decomposed if not unicodedata.combining(char))


def _property_type(property_type):
    name = _normalize(property_type.name) if property_type else ''
    # "Lote/Terreno" e "Sala Comercial" viram palavras soltas, para casar com as chaves acima.
    words = set(re.findall(r'[a-z]+', name))

    for keywords, label in PROPERTY_TYPE_KEYWORDS:
        if any(keyword in name if ' ' in keyword else keyword in words for keyword in keywords):
            return label

    return 'Residential / Home'
