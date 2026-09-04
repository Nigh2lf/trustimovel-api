from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Exporter, ExporterPlan, Feature, Fee

# Taxas que podem incidir sobre o imóvel; a tela de cadastro monta um campo para cada uma.
FEES = [
    'Condomínio',
    'IPTU',
    'Seguro',
    'Taxa de Incêndio',
]

FEATURES = [
    'Academia',
    'Água de Concessionária',
    'Água quente de reservatório',
    'Agua',
    'Aquecimento a gás',
    'Ar Condicionado',
    'Área de serviço',
    'Banda larga para internet',
    'Bico de Água Fácil acesso',
    'Cabina',
    'Cachoeira',
    'Câmera de Vídeo',
    'Campo de futebol',
    'Campo de vôlei',
    'Cerca elétrica',
    'Churrasqueira',
    'Ciclovia',
    'Cozinha Planejada',
    'Despensa',
    'Escritório',
    'Espaço Gourmet',
    'Estabilizado',
    'Estrutura para cavalos',
    'Fonte',
    'Forno a lenha',
    'Fossa / ecológica',
    'Heda',
    'Hidromassagem',
    'Interfone',
    'Lago',
    'Lareira',
    'Lavabo',
    'Maternidades',
    'Nascimento solar',
    'Pergolado a Piscina',
    'Perto de escola',
    'Perto de mercado',
    'Piscina',
    'Playground',
    'Portaria / vigia',
    'Portão eletrônico',
    'Pousada / Flats',
    'Quadra de beach tênnis',
    'Quadra de tênis',
    'Quadra poliesportiva',
    'Redário',
    'Restaurante',
    'Riacho ao redor',
    'Sala de Ginástica',
    'Salão de festas',
    'Salão de jogos',
    'Sauna a vapor',
    'Sauna seca',
    'Segurança 24 hs',
]

# Cada exportador tem a própria tabela de planos; "Não" é a ausência de vínculo, então não vira plano.
EXPORTERS = [
    ('Petrópolis Imóveis', ['Básico', 'Destaque', 'Super Destaque']),
    ('Imóvel Web', ['Básico', 'Destaque', 'Super Destaque']),
    ('Mercado Livre', ['Prata', 'Ouro', 'Diamante']),
    ('Zip Anúncios', ['Básico']),
    ('Portal CRECI', ['Básico']),
    ('Buskaza', ['Básico', 'Premium']),
    ('Portal 123i', ['Básico']),
    ('Portal Casa Mineira', ['Básico', 'Destaque', 'Super Destaque']),
    ('Compre Alugue Agora', ['Básico']),
    ('Juiz de Fora Imóveis', ['Básico', 'Destaque']),
    ('Teresópolis Imóveis', ['Básico', 'Destaque', 'Super Destaque']),
    ('Desapega Imóveis', ['Básico', 'Destaque']),
    (
        'ZAP Imóveis',
        [
            'Básico',
            'Destaque',
            'Super Destaque',
            'Destaque Premium',
            'Destaque Especial',
            'Destaque Triplo',
        ],
    ),
    (
        'Viva Real',
        [
            'Básico',
            'Destaque',
            'Super Destaque',
            'Destaque Premium',
            'Destaque Especial',
            'Destaque Triplo',
        ],
    ),
    ('OLX', ['Básico']),
    ('Chaves na Mão', ['Básico', 'Destaque', 'Super Destaque']),
    ('Landly', ['Básico', 'Destaque', 'Super Destaque']),
]


class Command(BaseCommand):
    help = 'Popula os catálogos de infraestruturas, taxas e exportadores com seus planos'

    @transaction.atomic
    def handle(self, *args, **options):
        self._create_features()
        self._create_fees()
        self._create_exporters()

        self.stdout.write(self.style.SUCCESS('Seed concluído.'))

    def _create_fees(self):
        created = 0

        for name in FEES:
            _instance, was_created = Fee.objects.get_or_create(name=name)
            created += int(was_created)

        self.stdout.write(f'Taxas: {created} criadas, {Fee.objects.count()} no catálogo')

    def _create_features(self):
        # A lista abaixo é a infraestrutura do imóvel; a do condomínio é cadastrada à parte.
        existing = set(
            Feature.objects.filter(type=Feature.Type.PROPERTY).values_list('name', flat=True)
        )
        new_features = [
            Feature(name=name, type=Feature.Type.PROPERTY)
            for name in FEATURES
            if name not in existing
        ]

        Feature.objects.bulk_create(new_features)
        self.stdout.write(f'Infraestruturas: {len(new_features)} criadas, {len(existing)} já existiam')

    def _create_exporters(self):
        created_exporters = 0
        created_plans = 0

        for name, plans in EXPORTERS:
            exporter, was_created = Exporter.objects.get_or_create(name=name)
            created_exporters += int(was_created)
            existing = set(exporter.plans.values_list('name', flat=True))

            new_plans = [
                ExporterPlan(exporter=exporter, name=plan, position=position)
                for position, plan in enumerate(plans, start=1)
                if plan not in existing
            ]

            ExporterPlan.objects.bulk_create(new_plans)
            created_plans += len(new_plans)

        self.stdout.write(
            f'Exportadores: {created_exporters} criados, {created_plans} planos criados'
        )
