import random
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    Agency,
    Fee,
    Neighborhood,
    Property,
    PropertyFee,
    PropertyPrice,
    PropertyType,
)

# Rótulos iguais aos do VRSync (ver seedpropertytypes).
PROPERTY_TYPES = ['Casa', 'Apartamento', 'Cobertura', 'Lote/Terreno', 'Sala/Conjunto']
OWNER_NAMES = [
    'Ana Souza',
    'Bruno Carvalho',
    'Carla Menezes',
    'Diego Ramos',
    'Elaine Prado',
    'Fábio Nogueira',
]
STREET_NAMES = [
    'Rua das Acácias',
    'Avenida Brasil',
    'Rua Marechal Deodoro',
    'Alameda dos Ipês',
    'Travessa São João',
    'Avenida Beira-Mar',
]


class Command(BaseCommand):
    help = 'Cria imóveis de teste para uma imobiliária, com valores, taxas e bairro sorteados'

    def add_arguments(self, parser):
        parser.add_argument('--count', dest='count', type=int, default=20, help='Quantidade de imóveis')
        parser.add_argument('--agency', dest='agency', help='Nome da imobiliária (padrão: a única cadastrada)')
        parser.add_argument('--seed', dest='seed', type=int, default=42, help='Semente do sorteio')

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(options['seed'])

        agency = self._get_agency(options['agency'])
        property_types = self._get_property_types()
        neighborhoods = list(
            Neighborhood.objects.select_related('city').order_by('?')[: options['count']]
        )

        if not neighborhoods:
            raise CommandError('Nenhum bairro cadastrado. Rode "manage.py seedlocations" antes.')

        for index in range(options['count']):
            neighborhood = neighborhoods[index % len(neighborhoods)]
            property_type = rng.choice(property_types)
            instance = self._create_property(rng, agency, property_type, neighborhood)
            self._create_prices(rng, instance)
            self._create_fees(rng, instance)

        self.stdout.write(
            self.style.SUCCESS(f'{options["count"]} imóveis criados para {agency.name}.')
        )

    def _get_agency(self, name):
        if name:
            agency = Agency.objects.filter(name=name).first()

            if agency is None:
                raise CommandError(f'Imobiliária "{name}" não encontrada.')

            return agency

        agencies = list(Agency.objects.all()[:2])

        if len(agencies) != 1:
            raise CommandError('Informe --agency: nenhuma ou mais de uma imobiliária cadastrada.')

        return agencies[0]

    def _get_property_types(self):
        for name in PROPERTY_TYPES:
            PropertyType.objects.get_or_create(name=name)

        return list(PropertyType.objects.filter(name__in=PROPERTY_TYPES))

    def _create_property(self, rng, agency, property_type, neighborhood):
        area = Decimal(rng.randrange(60, 600))
        bedrooms = rng.randint(1, 5)

        return Property.objects.create(
            agency=agency,
            type=property_type,
            neighborhood=neighborhood,
            name=f'{property_type.name} em {neighborhood.name}',
            description=(
                f'{property_type.name} para teste em {neighborhood.name}, '
                f'{neighborhood.city.name}/{neighborhood.city.state.abbreviation}.'
            ),
            address=rng.choice(STREET_NAMES),
            number=str(rng.randrange(10, 2000)),
            complement=rng.choice(['', 'Apto 101', 'Bloco B', 'Fundos']),
            zip_code=f'{rng.randrange(10000, 99999)}-{rng.randrange(100, 999)}',
            owner_name=rng.choice(OWNER_NAMES),
            area=area,
            built_area=area - Decimal(rng.randrange(10, 50)),
            bedrooms=bedrooms,
            suites=rng.randint(0, bedrooms),
            bathrooms=rng.randint(1, 4),
            parking_spaces=rng.randint(0, 4),
            featured=rng.random() < 0.25,
            exclusive=rng.random() < 0.2,
            accepts_trade=rng.random() < 0.3,
            views_count=rng.randrange(0, 500),
        )

    def _create_prices(self, rng, instance):
        # Todo imóvel de teste tem venda ou locação; parte tem os dois.
        purposes = [PropertyPrice.Purpose.SALE] if rng.random() < 0.6 else [PropertyPrice.Purpose.RENT]

        if rng.random() < 0.3:
            purposes = [PropertyPrice.Purpose.SALE, PropertyPrice.Purpose.RENT]

        for purpose in purposes:
            amount = (
                Decimal(rng.randrange(250, 2500) * 1000)
                if purpose == PropertyPrice.Purpose.SALE
                else Decimal(rng.randrange(1200, 9000))
            )
            PropertyPrice.objects.create(property=instance, purpose=purpose, amount=amount)

    def _create_fees(self, rng, instance):
        property_tax, _ = Fee.objects.get_or_create(name='IPTU')

        PropertyFee.objects.create(
            property=instance,
            fee=property_tax,
            amount=Decimal(rng.randrange(400, 6000)),
        )

        if rng.random() < 0.5:
            condominium, _ = Fee.objects.get_or_create(name='Condomínio')
            PropertyFee.objects.create(
                property=instance,
                fee=condominium,
                amount=Decimal(rng.randrange(300, 2500)),
            )
