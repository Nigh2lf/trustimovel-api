from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Agency, Condominium, Neighborhood, Owner

OWNERS = [
    ('Ana Souza', 'ana.souza@exemplo.com.br', '(24) 99812-4477'),
    ('Bruno Carvalho', 'bruno.carvalho@exemplo.com.br', '(24) 99745-3120'),
    ('Carla Menezes', 'carla.menezes@exemplo.com.br', '(21) 98633-9014'),
    ('Diego Ramos', 'diego.ramos@exemplo.com.br', '(24) 3237-8890'),
    ('Elaine Prado', 'elaine.prado@exemplo.com.br', '(21) 99521-6702'),
    ('Fábio Nogueira', 'fabio.nogueira@exemplo.com.br', '(24) 99408-2255'),
    ('Helena Vasconcelos', 'helena.vasconcelos@exemplo.com.br', '(24) 3242-1188'),
    ('Construtora Serra Azul Ltda', 'contato@serraazul.exemplo.com.br', '(24) 3512-7700'),
    ('Imobiliária Vale Verde S.A.', 'financeiro@valeverde.exemplo.com.br', '(21) 3388-4501'),
]

CONDOMINIUMS = [
    (
        'Residencial Vila Domênico',
        'Condomínio fechado com portaria 24 horas, piscina e salão de festas.',
        'Rua das Acácias, 120',
    ),
    (
        'Edifício Monte Belo',
        'Prédio residencial com elevador, salão de jogos e garagem coberta.',
        'Avenida Brasil, 850',
    ),
    (
        'Condomínio Alphaville Serrano',
        'Loteamento fechado com quadra poliesportiva, academia e área verde.',
        'Alameda dos Ipês, 45',
    ),
    (
        'Residencial Recanto das Águas',
        'Casas em condomínio com lago, churrasqueira e playground.',
        'Rua Marechal Deodoro, 970',
    ),
    (
        'Edifício Solar da Praça',
        'Apartamentos no centro, com portaria e sacada em todas as unidades.',
        'Travessa São João, 32',
    ),
    (
        'Condomínio Terras do Vale',
        'Chácaras em condomínio, com estrutura para cavalos e campo de futebol.',
        'Avenida Beira-Mar, 1500',
    ),
]


class Command(BaseCommand):
    help = 'Cria proprietários e condomínios de teste para uma imobiliária'

    def add_arguments(self, parser):
        parser.add_argument(
            '--agency',
            dest='agency',
            help='Nome da imobiliária (padrão: a única cadastrada)',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        agency = self._get_agency(options['agency'])

        created_owners = self._create_owners(agency)
        created_condominiums = self._create_condominiums(agency)

        self.stdout.write(
            self.style.SUCCESS(
                f'{agency.name}: {created_owners} proprietários e '
                f'{created_condominiums} condomínios criados.'
            )
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

    def _create_owners(self, agency):
        created = 0

        for name, email, phone in OWNERS:
            _instance, was_created = Owner.objects.get_or_create(
                agency=agency,
                name=name,
                defaults={'email': email, 'phone': phone},
            )
            created += int(was_created)

        return created

    def _create_condominiums(self, agency):
        neighborhoods = self._get_neighborhoods(agency, len(CONDOMINIUMS))
        created = 0

        for index, (name, description, address) in enumerate(CONDOMINIUMS):
            _instance, was_created = Condominium.objects.get_or_create(
                agency=agency,
                name=name,
                defaults={
                    'description': description,
                    'address': address,
                    'neighborhood': (
                        neighborhoods[index % len(neighborhoods)] if neighborhoods else None
                    ),
                },
            )
            created += int(was_created)

        return created

    def _get_neighborhoods(self, agency, quantity):
        # Prefere os bairros onde a imobiliária já tem imóvel, para o dado ficar coerente.
        chosen = list(
            Neighborhood.objects.filter(properties__agency=agency).distinct()[:quantity]
        )
        missing = quantity - len(chosen)

        if missing > 0:
            chosen += list(
                Neighborhood.objects.exclude(
                    id__in=[neighborhood.id for neighborhood in chosen]
                ).order_by('?')[:missing]
            )

        return chosen
