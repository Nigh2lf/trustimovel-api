from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import PropertyType

# Tipos aceitos pelo VRSync (VivaReal/Zap), na forma (elemento VRSync, rótulo).
# https://developers.grupozap.com/feeds/vrsync/elements/details.html#property-type
VRSYNC_PROPERTY_TYPES = [
    ('Residential / Apartment', 'Apartamento'),
    ('Residential / Home', 'Casa'),
    ('Residential / Condo', 'Casa de Condomínio'),
    ('Residential / Village House', 'Casa de Vila'),
    ('Residential / Farm Ranch', 'Chácara'),
    ('Residential / Penthouse', 'Cobertura'),
    ('Residential / Agricultural', 'Fazenda/Sítios/Chácaras'),
    ('Residential / Flat', 'Flat'),
    ('Residential / Kitnet', 'Kitnet/Conjugado'),
    ('Residential / Studio', 'Studio'),
    ('Residential / Loft', 'Loft'),
    ('Residential / Land Lot', 'Lote/Terreno'),
    ('Residential / Sobrado', 'Sobrado'),
    ('Commercial / Consultorio', 'Consultório'),
    ('Commercial / Edificio Residencial', 'Edifício Residencial'),
    ('Commercial / Industrial', 'Galpão/Depósito/Armazém'),
    ('Commercial / Garage', 'Garagem'),
    ('Commercial / Hotel', 'Hotel/Motel/Pousada'),
    ('Commercial / Building', 'Imóvel Comercial'),
    ('Commercial / Corporate Floor', 'Andar/Laje Corporativa'),
    # O VRSync repete Lote/Terreno em residencial e comercial; o catálogo guarda um registro só.
    ('Commercial / Land Lot', 'Lote/Terreno'),
    ('Commercial / Business', 'Ponto Comercial/Loja/Box'),
    ('Commercial / Edificio Comercial', 'Prédio/Edifício Inteiro'),
    ('Commercial / Office', 'Sala/Conjunto'),
]


class Command(BaseCommand):
    help = 'Popula os tipos de imóvel com a tabela de PropertyType do VRSync (VivaReal/Zap)'

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0

        for _code, name in VRSYNC_PROPERTY_TYPES:
            _instance, was_created = PropertyType.objects.get_or_create(name=name)

            if was_created:
                created += 1

        total = PropertyType.objects.count()
        self.stdout.write(
            self.style.SUCCESS(f'Tipos de imóvel: {created} criados, {total} no catálogo.')
        )
