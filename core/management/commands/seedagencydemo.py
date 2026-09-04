"""Volume de dados de demonstração para uma imobiliária: pessoas, imóveis, CRM e site.

Complementa os seeds existentes: `seedagencycatalogs` cria um punhado de proprietários e
condomínios fixos, este gera quantidade e espalha o histórico pelos últimos meses, para as
telas de listagem, de dashboard e de relatórios terem o que mostrar.
"""

import random
from datetime import datetime, time, timedelta
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from PIL import Image, ImageDraw

from core.models import (
    Agency,
    AgencyExporter,
    AgencyExporterPlan,
    BlogCategory,
    BlogPost,
    Broker,
    City,
    Client,
    CompanySection,
    Condominium,
    Deal,
    Exporter,
    Feature,
    Fee,
    Lead,
    LeadInteraction,
    Neighborhood,
    Owner,
    Property,
    PropertyExporter,
    PropertyFee,
    PropertyPhoto,
    PropertyPrice,
    PropertyType,
    ServiceTicket,
    ServiceTicketMessage,
    SiteBanner,
    Task,
)
from core.services.photos import build_thumbnail, resize_upload

COUNT_ARGUMENTS = [
    ('brokers', 100, 'Corretores'),
    ('owners', 120, 'Proprietários'),
    ('clients', 150, 'Clientes'),
    ('condominiums', 25, 'Condomínios'),
    ('properties', 150, 'Imóveis'),
    ('leads', 180, 'Leads'),
    ('tickets', 90, 'Atendimentos'),
    ('tasks', 140, 'Tarefas'),
    ('deals', 160, 'Negócios do funil'),
    ('posts', 24, 'Matérias do blog'),
    ('banners', 6, 'Banners do site'),
]

FIRST_NAMES = [
    'Adriana', 'Alexandre', 'Aline', 'Amanda', 'André', 'Antônio', 'Beatriz', 'Bruno',
    'Camila', 'Carlos', 'Carla', 'Cristiane', 'Daniel', 'Débora', 'Diego', 'Eduardo',
    'Elaine', 'Fabiana', 'Fábio', 'Felipe', 'Fernanda', 'Gabriel', 'Gustavo', 'Helena',
    'Henrique', 'Isabela', 'Jaqueline', 'João', 'Juliana', 'Larissa', 'Leonardo', 'Letícia',
    'Lucas', 'Luciana', 'Marcelo', 'Márcia', 'Mariana', 'Mateus', 'Michele', 'Natália',
    'Otávio', 'Patrícia', 'Paulo', 'Rafael', 'Raquel', 'Renata', 'Ricardo', 'Roberta',
    'Rodrigo', 'Sandra', 'Sérgio', 'Simone', 'Tatiane', 'Thiago', 'Vanessa', 'Vinícius',
    'Vitória', 'Wagner', 'Yasmin', 'Zélia',
]

LAST_NAMES = [
    'Almeida', 'Alves', 'Andrade', 'Araújo', 'Azevedo', 'Barbosa', 'Barros', 'Batista',
    'Cardoso', 'Carvalho', 'Castro', 'Cavalcanti', 'Correia', 'Costa', 'Dias', 'Duarte',
    'Farias', 'Fernandes', 'Ferreira', 'Fonseca', 'Freitas', 'Gomes', 'Gonçalves', 'Guimarães',
    'Lima', 'Lopes', 'Machado', 'Martins', 'Medeiros', 'Melo', 'Mendes', 'Menezes',
    'Moraes', 'Moreira', 'Nascimento', 'Nogueira', 'Nunes', 'Oliveira', 'Pereira', 'Pinheiro',
    'Prado', 'Queiroz', 'Ramos', 'Rezende', 'Ribeiro', 'Rocha', 'Rodrigues', 'Sampaio',
    'Santos', 'Silva', 'Siqueira', 'Souza', 'Teixeira', 'Vasconcelos', 'Vieira', 'Xavier',
]

COMPANY_NAMES = [
    'Construtora Serra Azul', 'Incorporadora Vale Verde', 'Patrimonial Monte Belo',
    'Administradora Terras do Vale', 'Holding Recanto das Águas', 'Empreendimentos Solar',
]

COMPANY_SUFFIXES = ['Ltda', 'S.A.', 'ME', 'Participações', 'Imóveis', 'Administração']

STREET_NAMES = [
    'Rua das Acácias', 'Avenida Brasil', 'Rua Marechal Deodoro', 'Alameda dos Ipês',
    'Travessa São João', 'Avenida Beira-Mar', 'Rua Sete de Setembro', 'Estrada do Contorno',
    'Rua Coronel Veiga', 'Avenida Koeler', 'Rua Teresa', 'Praça da Liberdade',
]

OCCUPATIONS = [
    'Advogado(a)', 'Analista de sistemas', 'Arquiteto(a)', 'Comerciante', 'Contador(a)',
    'Dentista', 'Empresário(a)', 'Enfermeiro(a)', 'Engenheiro(a)', 'Médico(a)',
    'Professor(a)', 'Publicitário(a)', 'Servidor(a) público', 'Aposentado(a)',
]

CONDOMINIUM_PREFIXES = [
    'Residencial', 'Edifício', 'Condomínio', 'Village', 'Portal', 'Reserva',
]

CONDOMINIUM_SUFFIXES = [
    'Vila Domênico', 'Monte Belo', 'Alphaville Serrano', 'Recanto das Águas', 'Solar da Praça',
    'Terras do Vale', 'Jardim das Palmeiras', 'Bosque Real', 'Serra Dourada', 'Lago Azul',
    'Mirante do Vale', 'Quinta da Boa Vista', 'Parque das Flores', 'Costa Verde',
    'Alto da Serra', 'Vista Alegre', 'Colina Park', 'Green Village', 'Vale dos Pinheiros',
    'Morada do Sol', 'Ilha Bela', 'Praia Grande', 'Campo Belo', 'Nova Suíça', 'Bela Vista',
]

BUDGET_RANGES = [
    'Até R$ 300 mil', 'R$ 300 a 500 mil', 'R$ 500 a 800 mil', 'R$ 800 mil a 1,2 mi',
    'R$ 1,2 a 2 mi', 'Acima de R$ 2 mi', 'Aluguel até R$ 2 mil', 'Aluguel de R$ 2 a 5 mil',
]

OWNER_NOTES = [
    'Prefere contato à tarde.',
    'Autoriza visitas com agendamento prévio.',
    'Chave na portaria do prédio.',
    'Imóvel de herança, documentação em regularização.',
    '',
    '',
]

LEAD_NOTES = [
    'Procura imóvel próximo ao centro, com garagem.',
    'Quer agendar visita no fim de semana.',
    'Já tem financiamento pré-aprovado.',
    'Prefere imóvel pronto para morar, sem reforma.',
    'Busca opção com aceitação de permuta.',
    'Precisa de pelo menos três quartos e área de lazer.',
    'Interesse em investimento para locação por temporada.',
    'Trabalha na região e quer reduzir o deslocamento.',
]

INTERACTION_TEXTS = [
    'Primeiro contato por telefone, cliente pediu retorno por WhatsApp.',
    'Enviada seleção de imóveis por e-mail.',
    'Visita agendada, aguardando confirmação.',
    'Cliente pediu para retomar o contato no próximo mês.',
    'Proposta apresentada, aguardando resposta do proprietário.',
    'Documentação solicitada para análise de crédito.',
]

TICKET_SUBJECTS = [
    'Dúvida sobre a documentação do imóvel',
    'Solicitação de visita',
    'Pedido de avaliação de imóvel',
    'Reajuste do contrato de locação',
    'Problema no imóvel alugado',
    'Interesse em anunciar imóvel',
    'Segunda via do boleto',
    'Informações sobre financiamento',
]

TASK_TITLES = [
    'Ligar para o cliente', 'Enviar proposta por e-mail', 'Visita ao imóvel',
    'Reunião de alinhamento', 'Retomar contato com o lead', 'Conferir documentação',
    'Negociar valor com o proprietário', 'Atualizar fotos do anúncio',
]

POST_TITLES = [
    'Como escolher o bairro certo para morar',
    'Documentos necessários para comprar um imóvel',
    'Financiamento imobiliário: o que muda em cada banco',
    'Vale a pena investir em imóvel para locação por temporada?',
    'Cinco reformas que valorizam o imóvel na hora da venda',
    'O que avaliar em uma visita antes de fechar negócio',
    'Aluguel ou compra: qual faz mais sentido hoje',
    'Entenda as taxas e impostos na compra do imóvel',
    'Imóvel na planta ou pronto: prós e contras',
    'Como preparar o imóvel para fotos que vendem',
    'Condomínio fechado: o que pesa na decisão',
    'Guia rápido do contrato de locação',
    'Permuta de imóveis: quando é um bom negócio',
    'Sinais de que é hora de trocar de imóvel',
    'Investir em lotes: o que analisar antes',
    'Casa ou apartamento para famílias grandes',
    'Como funciona a avaliação de um imóvel',
    'Erros comuns de quem vende o primeiro imóvel',
    'Imóveis comerciais: o que muda na negociação',
    'Reforma antes de alugar compensa?',
    'O papel do corretor na negociação',
    'Regularização de imóvel: por onde começar',
    'Seguro fiança ou fiador: qual escolher',
    'Mercado imobiliário na serra: o que esperar',
]

BANNER_TITLES = [
    'Imóveis em destaque na serra', 'Condições especiais de financiamento',
    'Aluguel por temporada com desconto', 'Lançamentos exclusivos',
    'Anuncie seu imóvel conosco', 'Avaliação gratuita do seu imóvel',
]

COMPANY_SECTIONS = [
    ('Quem somos', 'Atuamos há mais de vinte anos na intermediação de compra, venda e locação '
                   'de imóveis, com equipe própria de corretores e atendimento personalizado.'),
    ('Nossa missão', 'Aproximar pessoas do imóvel certo, com transparência em cada etapa da '
                     'negociação e segurança na documentação.'),
    ('Como trabalhamos', 'Da avaliação do imóvel ao pós-venda, acompanhamos o cliente em todo o '
                         'processo, com visitas agendadas e propostas registradas.'),
    ('Onde estamos', 'Escritório na região central, com atendimento presencial de segunda a '
                     'sexta e visitas agendadas aos sábados.'),
]

# Cidades preferidas para o dado ficar concentrado, como o de uma imobiliária real.
PREFERRED_CITIES = ['Petrópolis', 'Teresópolis', 'Rio de Janeiro', 'Niterói']

STAGE_PROBABILITIES = {
    Deal.Stage.QUALIFICATION: 10,
    Deal.Stage.VISIT_SCHEDULED: 25,
    Deal.Stage.VISIT_DONE: 40,
    Deal.Stage.PROPOSAL: 60,
    Deal.Stage.NEGOTIATION: 75,
    Deal.Stage.CLOSING: 90,
}

PHOTO_SIZE = (1200, 800)


class Command(BaseCommand):
    help = 'Popula uma imobiliária com dados de demonstração: pessoas, imóveis, CRM e site'

    def add_arguments(self, parser):
        parser.add_argument('--agency', dest='agency', help='Nome da imobiliária (padrão: a única cadastrada)')
        parser.add_argument('--seed', dest='seed', type=int, default=7, help='Semente do sorteio')
        parser.add_argument('--months', dest='months', type=int, default=14, help='Meses de histórico gerados')
        parser.add_argument('--photos', dest='photos', type=int, default=2, help='Fotos por imóvel (0 não gera)')

        for name, default, label in COUNT_ARGUMENTS:
            parser.add_argument(f'--{name}', dest=name, type=int, default=default, help=f'{label} a criar')

    @transaction.atomic
    def handle(self, *args, **options):
        self.rng = random.Random(options['seed'])
        self.today = timezone.localdate()
        self.days = max(options['months'], 1) * 30

        agency = self._get_agency(options['agency'])
        names = self._name_pool()
        neighborhoods = self._get_neighborhoods()

        brokers = self._create_brokers(agency, names, options['brokers'])
        owners = self._create_owners(agency, names, neighborhoods, options['owners'])
        clients = self._create_clients(agency, names, neighborhoods, options['clients'])
        condominiums = self._create_condominiums(agency, neighborhoods, options['condominiums'])
        exporter_plans = self._create_agency_exporters(agency)

        # Contagem zero pula o bloco, mas os seguintes continuam apontando para o que já existe.
        broker_pool = brokers or self._existing(Broker, agency)
        owner_pool = owners or self._existing(Owner, agency)
        condominium_pool = condominiums or self._existing(Condominium, agency)

        properties = self._create_properties(
            agency, neighborhoods, condominium_pool, broker_pool, owner_pool, exporter_plans, options
        )
        leads = self._create_leads(agency, broker_pool, options['leads'])

        property_pool = properties or self._existing(Property, agency)
        lead_pool = leads or self._existing(Lead, agency)

        deals = self._create_deals(agency, broker_pool, lead_pool, property_pool, options['deals'])
        tickets = self._create_tickets(agency, broker_pool, property_pool, options['tickets'])
        tasks = self._create_tasks(
            agency, broker_pool, lead_pool, deals, property_pool, options['tasks']
        )
        posts = self._create_blog(agency, options['posts'])
        banners = self._create_banners(agency, options['banners'])
        sections = self._create_company_sections(agency)

        self._report(
            agency,
            [
                ('corretores', brokers),
                ('proprietários', owners),
                ('clientes', clients),
                ('condomínios', condominiums),
                ('imóveis', properties),
                ('leads', leads),
                ('negócios', deals),
                ('atendimentos', tickets),
                ('tarefas', tasks),
                ('matérias do blog', posts),
                ('banners', banners),
                ('seções da empresa', sections),
            ],
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

    def _existing(self, model, agency):
        return list(model.objects.filter(agency_id=agency.id, deleted_at__isnull=True))

    def _report(self, agency, blocks):
        for label, items in blocks:
            self.stdout.write(f'  {len(items):>4} {label}')

        self.stdout.write(
            self.style.SUCCESS(
                f'Dados de demonstração criados para {agency.name}. '
                'Rodar de novo acrescenta outro lote, não substitui o atual.'
            )
        )

    def _name_pool(self):
        pool = [f'{first} {last}' for first in FIRST_NAMES for last in LAST_NAMES]
        self.rng.shuffle(pool)

        return iter(pool)

    def _get_neighborhoods(self):
        cities = City.objects.filter(name__in=PREFERRED_CITIES, state__abbreviation='RJ')
        chosen = list(
            Neighborhood.objects.filter(city__in=cities).select_related('city__state')
        )

        if len(chosen) < 20:
            chosen += list(
                Neighborhood.objects.exclude(id__in=[item.id for item in chosen])
                .select_related('city__state')
                .order_by('?')[:100]
            )

        if not chosen:
            raise CommandError('Nenhum bairro cadastrado. Rode "manage.py seedlocations" antes.')

        return chosen

    def _phone(self):
        return f'(24) 9{self.rng.randrange(1000, 9999)}-{self.rng.randrange(1000, 9999)}'

    def _email(self, name, index):
        return f'{slugify(name)}.{index}@exemplo.com.br'

    def _document(self):
        """CPF com dígitos verificadores corretos, para não travar validação de máscara."""
        digits = [self.rng.randrange(0, 9) for _ in range(9)]

        for weight in (10, 11):
            total = sum(digit * (weight + position - 1) for position, digit in enumerate(digits, start=1))
            remainder = (total * 10) % 11
            digits.append(0 if remainder == 10 else remainder)

        body = ''.join(str(digit) for digit in digits)

        return f'{body[:3]}.{body[3:6]}.{body[6:9]}-{body[9:]}'

    def _zip_code(self):
        return f'{self.rng.randrange(20000, 28999)}-{self.rng.randrange(100, 999):03d}'

    def _weighted(self, items):
        """Sorteio enviesado para o início da lista: concentra a atividade em poucos nomes."""
        if not items:
            return None

        index = min(int(abs(self.rng.gauss(0, len(items) / 4))), len(items) - 1)

        return items[index]

    def _past_date(self, days=None):
        return self.today - timedelta(days=self.rng.randrange(0, days or self.days))

    def _as_datetime(self, date):
        moment = time(hour=self.rng.randrange(8, 20), minute=self.rng.randrange(0, 60))

        return timezone.make_aware(datetime.combine(date, moment))

    def _backdate(self, model, pairs):
        """`created_at` é auto_now_add: só um update posterior espalha o histórico no tempo."""
        for instance, date in pairs:
            instance.created_at = self._as_datetime(date)

        model.objects.bulk_update([instance for instance, _ in pairs], ['created_at'], batch_size=200)

    def _next_numeric_code(self, model, agency):
        codes = model.objects.filter(agency_id=agency.id, code__regex=r'^[0-9]+$').values_list(
            'code', flat=True
        )

        return max((int(code) for code in codes), default=0) + 1

    def _take_names(self, model, agency, names, count):
        """Corretor e proprietário têm nome único por imobiliária: pula o que já está cadastrado."""
        used = set(model.objects.filter(agency_id=agency.id).values_list('name', flat=True))
        chosen = []

        while len(chosen) < count:
            name = next(names, None)

            if name is None:
                break

            if name not in used:
                used.add(name)
                chosen.append(name)

        return chosen

    def _company_pool(self):
        pool = [f'{name} {suffix}' for name in COMPANY_NAMES for suffix in COMPANY_SUFFIXES]
        self.rng.shuffle(pool)

        return iter(pool)

    def _create_brokers(self, agency, names, count):
        brokers = [
            Broker(agency=agency, name=name, email=self._email(name, index), phone=self._phone())
            for index, name in enumerate(self._take_names(Broker, agency, names, count))
        ]

        return Broker.objects.bulk_create(brokers)

    def _create_owners(self, agency, names, neighborhoods, count):
        # Uma parcela dos proprietários é pessoa jurídica, como acontece na carteira real.
        companies = min(int(count * 0.12), len(COMPANY_NAMES) * len(COMPANY_SUFFIXES))
        chosen = self._take_names(Owner, agency, self._company_pool(), companies)
        chosen += self._take_names(Owner, agency, names, count - len(chosen))
        self.rng.shuffle(chosen)

        owners = [
            Owner(
                agency=agency,
                name=name,
                spouse=next(names) if self.rng.random() < 0.4 else '',
                email=self._email(name, index),
                phone=self._phone(),
                mobile=self._phone(),
                business_phone=self._phone() if self.rng.random() < 0.3 else '',
                document=self._document(),
                birth_date=self.today - timedelta(days=self.rng.randrange(9000, 25000)),
                address=self.rng.choice(STREET_NAMES),
                number=str(self.rng.randrange(10, 2000)),
                zip_code=self._zip_code(),
                neighborhood=self.rng.choice(neighborhoods),
                notes=self.rng.choice(OWNER_NOTES),
            )
            for index, name in enumerate(chosen)
        ]

        return Owner.objects.bulk_create(owners)

    def _create_clients(self, agency, names, neighborhoods, count):
        start = self._next_numeric_code(Client, agency)
        clients = []

        for index in range(count):
            name = next(names)
            neighborhood = self.rng.choice(neighborhoods)
            clients.append(
                Client(
                    agency=agency,
                    code=str(start + index),
                    name=name,
                    email=self._email(name, index),
                    phone=self._phone(),
                    document=self._document(),
                    type=self.rng.choice(Client.Type.values),
                    birth_date=self.today - timedelta(days=self.rng.randrange(8000, 22000)),
                    occupation=self.rng.choice(OCCUPATIONS),
                    neighborhood=neighborhood,
                    address=self.rng.choice(STREET_NAMES),
                    number=str(self.rng.randrange(10, 2000)),
                    zip_code=self._zip_code(),
                    is_active=self.rng.random() < 0.92,
                )
            )

        created = Client.objects.bulk_create(clients)
        self._backdate(Client, [(client, self._past_date()) for client in created])

        return created

    def _create_condominiums(self, agency, neighborhoods, count):
        names = [
            f'{prefix} {suffix}'
            for prefix in CONDOMINIUM_PREFIXES
            for suffix in CONDOMINIUM_SUFFIXES
        ]
        self.rng.shuffle(names)
        existing = set(Condominium.objects.filter(agency=agency).values_list('name', flat=True))
        chosen = [name for name in names if name not in existing][:count]

        condominiums = [
            Condominium(
                agency=agency,
                name=name,
                neighborhood=self.rng.choice(neighborhoods),
                address=f'{self.rng.choice(STREET_NAMES)}, {self.rng.randrange(10, 2000)}',
                description=(
                    'Condomínio com portaria 24 horas, área de lazer completa e '
                    'vagas cobertas para os moradores.'
                ),
            )
            for name in chosen
        ]

        return Condominium.objects.bulk_create(condominiums)

    def _create_agency_exporters(self, agency):
        """Habilita portais para a imobiliária e devolve os planos disponíveis para os imóveis."""
        exporters = list(Exporter.objects.filter(deleted_at__isnull=True).order_by('name')[:8])
        plans = []

        for exporter in exporters:
            agency_exporter, _ = AgencyExporter.objects.get_or_create(
                agency=agency, exporter=exporter
            )

            for plan in exporter.plans.all():
                AgencyExporterPlan.objects.get_or_create(
                    agency_exporter=agency_exporter,
                    plan=plan,
                    defaults={'limit': self.rng.randrange(20, 120)},
                )
                plans.append(plan)

        return plans

    def _create_properties(self, agency, neighborhoods, condominiums, brokers, owners, plans, options):
        count = options['properties']
        types = list(PropertyType.objects.all())
        features = list(Feature.objects.filter(type=Feature.Type.PROPERTY))
        fees = list(Fee.objects.all())
        start = self._next_numeric_code(Property, agency)
        created = []

        if not types:
            raise CommandError('Nenhum tipo de imóvel. Rode "manage.py seedpropertytypes" antes.')

        for index in range(count):
            neighborhood = self.rng.choice(neighborhoods)
            property_type = self.rng.choice(types)
            instance = self._build_property(
                agency, str(start + index), property_type, neighborhood, condominiums, brokers, owners
            )
            instance.save()

            self._create_prices(instance)
            self._create_fees(instance, fees)
            self._create_property_exporters(instance, plans)

            if features:
                instance.features.set(self.rng.sample(features, self.rng.randint(3, 10)))

            if options['photos']:
                self._create_photos(instance, options['photos'])

            created.append(instance)

        self._backdate(Property, [(item, self._past_date()) for item in created])

        return created

    def _build_property(self, agency, code, property_type, neighborhood, condominiums, brokers, owners):
        area = Decimal(self.rng.randrange(45, 700))
        bedrooms = self.rng.randint(1, 5)
        # Só uma parte da carteira fica dentro de condomínio; o resto é imóvel de rua.
        condominium = self.rng.choice(condominiums) if condominiums and self.rng.random() < 0.35 else None
        owner = self._weighted(owners)

        return Property(
            agency=agency,
            code=code,
            type=property_type,
            neighborhood=neighborhood,
            condominium=condominium,
            broker=self._weighted(brokers),
            owner=owner,
            name=f'{property_type.name} em {neighborhood.name}',
            description=(
                f'{property_type.name} em {neighborhood.name}, {neighborhood.city.name}/'
                f'{neighborhood.city.state.abbreviation}, com {bedrooms} quarto(s) e '
                f'{area} m² de área total.'
            ),
            address=self.rng.choice(STREET_NAMES),
            number=str(self.rng.randrange(10, 2000)),
            complement=self.rng.choice(['', '', 'Apto 101', 'Bloco B', 'Casa 2', 'Fundos']),
            zip_code=self._zip_code(),
            region=neighborhood.city.name,
            owner_name=owner.name if owner else '',
            contact_phone=self._phone(),
            area=area,
            built_area=area - Decimal(self.rng.randrange(5, 40)),
            bedrooms=bedrooms,
            suites=self.rng.randint(0, bedrooms),
            bathrooms=self.rng.randint(1, 4),
            living_rooms=self.rng.randint(1, 3),
            parking_spaces=self.rng.randint(0, 4),
            guests=self.rng.randint(0, 8),
            is_active=self.rng.random() < 0.9,
            featured=self.rng.random() < 0.2,
            exclusive=self.rng.random() < 0.18,
            reserved=self.rng.random() < 0.08,
            under_construction=self.rng.random() < 0.1,
            opportunity=self.rng.random() < 0.15,
            on_site=self.rng.random() < 0.75,
            accepts_trade=self.rng.random() < 0.3,
            views_count=self.rng.randrange(0, 900),
        )

    def _create_prices(self, instance):
        purposes = [PropertyPrice.Purpose.SALE] if self.rng.random() < 0.6 else [PropertyPrice.Purpose.RENT]

        if self.rng.random() < 0.3:
            purposes = [PropertyPrice.Purpose.SALE, PropertyPrice.Purpose.RENT]

        if self.rng.random() < 0.1:
            purposes.append(PropertyPrice.Purpose.SEASONAL)

        PropertyPrice.objects.bulk_create(
            [
                PropertyPrice(property=instance, purpose=purpose, amount=self._price_for(purpose))
                for purpose in purposes
            ]
        )

    def _price_for(self, purpose):
        if purpose == PropertyPrice.Purpose.SALE:
            return Decimal(self.rng.randrange(180, 3500) * 1000)

        if purpose == PropertyPrice.Purpose.RENT:
            return Decimal(self.rng.randrange(1200, 12000))

        return Decimal(self.rng.randrange(250, 2500))

    def _create_fees(self, instance, fees):
        if not fees:
            return

        chosen = self.rng.sample(fees, self.rng.randint(1, min(3, len(fees))))

        PropertyFee.objects.bulk_create(
            [
                PropertyFee(property=instance, fee=fee, amount=Decimal(self.rng.randrange(120, 6000)))
                for fee in chosen
            ]
        )

    def _create_property_exporters(self, instance, plans):
        if not plans or self.rng.random() < 0.35:
            return

        chosen = self.rng.sample(plans, min(self.rng.randint(1, 3), len(plans)))
        seen = set()

        for plan in chosen:
            # A unicidade é por imóvel e portal: dois planos do mesmo portal não convivem.
            if plan.exporter_id in seen:
                continue

            seen.add(plan.exporter_id)
            PropertyExporter.objects.create(
                property=instance, exporter_id=plan.exporter_id, plan=plan
            )

    def _create_photos(self, instance, count):
        for position in range(1, count + 1):
            content = self._placeholder_image(f'{instance.code}-{position}')
            photo = PropertyPhoto(property=instance, position=position, is_main=position == 1)
            photo.image.save(content.name, content, save=False)
            photo.save()

            if photo.is_main:
                build_thumbnail(photo)

    def _placeholder_image(self, label):
        """Imagem sintética: a galeria precisa de arquivo, não de foto de imóvel de verdade."""
        hue = self.rng.randrange(0, 255)
        width, height = PHOTO_SIZE
        horizon = self.rng.randrange(395, 465)
        image = Image.new('HSV', PHOTO_SIZE, (hue, 70, 225))
        draw = ImageDraw.Draw(image)

        draw.rectangle([0, horizon, width, height], fill=(hue, 130, 120))
        draw.polygon(
            [(160, horizon), (width // 2, horizon - self.rng.randrange(180, 300)), (width - 160, horizon)],
            fill=(hue, 60, 250),
        )
        draw.rectangle([250, horizon, width - 250, height - 40], fill=(hue, 35, 240))

        for x in range(330, width - 330, 190):
            draw.rectangle([x, horizon + 70, x + 120, horizon + 190], fill=(hue, 160, 95))

        draw.rectangle([width // 2 - 60, horizon + 225, width // 2 + 60, height - 30], fill=(hue, 170, 80))

        buffer = BytesIO()
        image.convert('RGB').save(buffer, format='PNG')

        return resize_upload(ContentFile(buffer.getvalue(), name=f'{label}.png'))

    def _create_leads(self, agency, brokers, count):
        codes = Lead.objects.filter(agency=agency, code__regex=r'^LEAD[0-9]+$').values_list(
            'code', flat=True
        )
        start = max((int(code[4:]) for code in codes), default=0) + 1
        names = self._name_pool()
        type_names = list(PropertyType.objects.values_list('name', flat=True)[:8]) or ['Casa']
        leads = []
        dates = []

        for index in range(count):
            name = next(names)
            created = self._past_date()
            leads.append(
                Lead(
                    agency=agency,
                    code=f'LEAD{start + index:03d}',
                    name=name,
                    email=self._email(name, index),
                    phone=self._phone(),
                    source=self.rng.choice(Lead.Source.values),
                    status=self.rng.choice(Lead.Status.values),
                    interest=self.rng.choice(Lead.Interest.values),
                    property_type=self.rng.choice(type_names),
                    budget=self.rng.choice(BUDGET_RANGES),
                    city=self.rng.choice(PREFERRED_CITIES),
                    state='RJ',
                    responsible=self._weighted(brokers),
                    observations=self.rng.choice(LEAD_NOTES),
                    last_contact_at=created + timedelta(days=self.rng.randrange(0, 20)),
                )
            )
            dates.append(created)

        created_leads = Lead.objects.bulk_create(leads)
        self._backdate(Lead, list(zip(created_leads, dates)))
        self._create_interactions(created_leads)

        return created_leads

    def _create_interactions(self, leads):
        interactions = []

        for lead in leads:
            for _ in range(self.rng.randint(0, 3)):
                interactions.append(
                    LeadInteraction(
                        lead=lead,
                        author_name=lead.responsible.name if lead.responsible_id else 'Atendimento',
                        text=self.rng.choice(INTERACTION_TEXTS),
                    )
                )

        LeadInteraction.objects.bulk_create(interactions)

    def _create_deals(self, agency, brokers, leads, properties, count):
        names = self._name_pool()
        deals = []
        dates = []

        for _ in range(count):
            lead = self.rng.choice(leads) if leads and self.rng.random() < 0.6 else None
            instance = self.rng.choice(properties) if properties else None
            created = self._past_date()
            deal = Deal(
                agency=agency,
                title=f'Negociação {instance.name}' if instance else 'Negociação de imóvel',
                client_name=lead.name if lead else next(names),
                value=self._deal_value(),
                responsible=self._weighted(brokers),
                origin=lead.source if lead else self.rng.choice(Lead.Source.values),
                type=self.rng.choice(Deal.Type.values),
                property_code=instance.code if instance else '',
                description='Negociação registrada pelo funil de vendas.',
                estimated_close=created + timedelta(days=self.rng.randrange(20, 120)),
                lead=lead,
            )
            self._apply_outcome(deal, created)
            deals.append(deal)
            dates.append(created)

        created_deals = Deal.objects.bulk_create(deals)
        self._backdate(Deal, list(zip(created_deals, dates)))
        self._mark_converted_leads(created_deals)

        return created_deals

    def _deal_value(self):
        return Decimal(self.rng.randrange(150, 3200) * 1000)

    def _apply_outcome(self, deal, created):
        """Encerra parte dos negócios sem passar de hoje; o resto continua no quadro do funil."""
        window = (self.today - created).days
        draw = self.rng.random()

        if window < 5 or draw > 0.72:
            deal.stage = self._open_stage()
            deal.probability = STAGE_PROBABILITIES[deal.stage]
            return

        deal.closed_at = created + timedelta(days=self.rng.randrange(3, min(window, 100) + 1))

        if draw < 0.45:
            deal.outcome = Deal.Outcome.WON
            deal.stage = Deal.Stage.CLOSING
            deal.probability = 100
        else:
            deal.outcome = Deal.Outcome.LOST
            deal.stage = self._open_stage()
            deal.loss_reason = self.rng.choice(Deal.LossReason.values)
            deal.probability = 0

    def _open_stage(self):
        stages = Deal.Stage.values

        return stages[min(int(abs(self.rng.gauss(0, 2.2))), len(stages) - 1)]

    def _mark_converted_leads(self, deals):
        won = [deal.lead_id for deal in deals if deal.outcome == Deal.Outcome.WON and deal.lead_id]

        Lead.objects.filter(id__in=won).update(status=Lead.Status.CONVERTED)

    def _create_tickets(self, agency, brokers, properties, count):
        year = self.today.year
        prefix = f'ATD-{year}-'
        existing = ServiceTicket.objects.filter(
            agency=agency, protocol__startswith=prefix
        ).values_list('protocol', flat=True)
        start = max(
            (int(protocol[len(prefix):]) for protocol in existing if protocol[len(prefix):].isdigit()),
            default=0,
        ) + 1
        names = self._name_pool()
        tickets = []
        dates = []

        for index in range(count):
            name = next(names)
            instance = self.rng.choice(properties) if properties and self.rng.random() < 0.6 else None
            tickets.append(
                ServiceTicket(
                    agency=agency,
                    protocol=f'{prefix}{start + index:03d}',
                    client_name=name,
                    email=self._email(name, index),
                    phone=self._phone(),
                    subject=self.rng.choice(TICKET_SUBJECTS),
                    category=self.rng.choice(ServiceTicket.Category.values),
                    status=self.rng.choice(ServiceTicket.Status.values),
                    priority=self.rng.choice(ServiceTicket.Priority.values),
                    responsible=self._weighted(brokers),
                    property_code=instance.code if instance else '',
                    description='Solicitação registrada pelo canal de atendimento.',
                )
            )
            dates.append(self._past_date(180))

        created = ServiceTicket.objects.bulk_create(tickets)
        self._backdate(ServiceTicket, list(zip(created, dates)))
        self._create_ticket_messages(created)

        return created

    def _create_ticket_messages(self, tickets):
        messages = []

        for ticket in tickets:
            messages.append(
                ServiceTicketMessage(
                    ticket=ticket,
                    author_name=ticket.client_name,
                    author_type=ServiceTicketMessage.AuthorType.CLIENT,
                    message=ticket.subject,
                )
            )

            if ticket.status != ServiceTicket.Status.NEW:
                messages.append(
                    ServiceTicketMessage(
                        ticket=ticket,
                        author_name=ticket.responsible.name if ticket.responsible_id else 'Atendimento',
                        author_type=ServiceTicketMessage.AuthorType.AGENT,
                        message='Recebemos sua solicitação e já estamos verificando as informações.',
                    )
                )

        ServiceTicketMessage.objects.bulk_create(messages)

    def _create_tasks(self, agency, brokers, leads, deals, properties, count):
        tasks = []

        for _ in range(count):
            due_date = self.today + timedelta(days=self.rng.randrange(-90, 30))
            task_type = self.rng.choice(Task.Type.values)
            instance = self.rng.choice(properties) if properties else None
            tasks.append(
                Task(
                    agency=agency,
                    title=self.rng.choice(TASK_TITLES),
                    description='Compromisso registrado na agenda da equipe.',
                    type=task_type,
                    status=self._task_status(due_date),
                    priority=self.rng.choice(Task.Priority.values),
                    responsible=self._weighted(brokers),
                    due_date=due_date,
                    due_time=time(hour=self.rng.randrange(8, 19), minute=self.rng.choice([0, 15, 30, 45])),
                    lead=self.rng.choice(leads) if leads and self.rng.random() < 0.4 else None,
                    deal=self.rng.choice(deals) if deals and self.rng.random() < 0.3 else None,
                    property_code=instance.code if instance and task_type == Task.Type.VISIT else '',
                )
            )

        return Task.objects.bulk_create(tasks)

    def _task_status(self, due_date):
        if due_date < self.today:
            return Task.Status.DONE if self.rng.random() < 0.75 else Task.Status.PENDING

        return self.rng.choice([Task.Status.PENDING, Task.Status.IN_PROGRESS])

    def _create_blog(self, agency, count):
        categories = self._create_blog_categories(agency)
        existing = set(BlogPost.objects.filter(agency=agency).values_list('slug', flat=True))
        posts = []

        for title in POST_TITLES[:count]:
            slug = slugify(title)[:180]

            if slug in existing:
                continue

            posts.append(
                BlogPost(
                    agency=agency,
                    category=self.rng.choice(categories),
                    title=title,
                    slug=slug,
                    published_at=self._past_date(365),
                    description=(
                        f'<p>{title}. Neste conteúdo reunimos as dúvidas mais frequentes de '
                        'quem está comprando, vendendo ou alugando um imóvel na região.</p>'
                    ),
                    meta_title=title[:60],
                    meta_description=f'{title} — guia prático da nossa equipe.'[:160],
                    tags=self.rng.sample(['imoveis', 'financiamento', 'locacao', 'dicas', 'mercado'], 3),
                    status=BlogPost.Status.PUBLISHED if self.rng.random() < 0.8 else BlogPost.Status.DRAFT,
                )
            )

        return BlogPost.objects.bulk_create(posts)

    def _create_blog_categories(self, agency):
        names = ['Mercado', 'Dicas de compra', 'Locação', 'Financiamento', 'Decoração', 'Documentação']

        for name in names:
            BlogCategory.objects.get_or_create(agency=agency, name=name)

        return list(BlogCategory.objects.filter(agency=agency, deleted_at__isnull=True))

    def _create_banners(self, agency, count):
        existing = set(agency.site_banners.values_list('title', flat=True))
        created = []

        for index, title in enumerate(BANNER_TITLES[:count]):
            if title in existing:
                continue

            # O banner exige imagem, então não entra em bulk_create como os demais cadastros.
            banner = SiteBanner(
                agency=agency,
                title=title,
                link='https://exemplo.com.br/imoveis',
                is_active=self.rng.random() < 0.85,
            )
            content = self._placeholder_image(f'banner-{index}')
            banner.image.save(content.name, content, save=False)
            banner.save()
            created.append(banner)

        return created

    def _create_company_sections(self, agency):
        created = []

        for title, text in COMPANY_SECTIONS:
            section, was_created = CompanySection.objects.get_or_create(
                agency=agency, title=title, defaults={'text': text}
            )

            if was_created:
                created.append(section)

        return created

