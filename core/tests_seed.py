"""Testes do comando de dados de demonstração: volume, escopo e repetição sem quebrar."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Agency,
    Broker,
    City,
    Client,
    Condominium,
    Country,
    Deal,
    Lead,
    Neighborhood,
    Owner,
    Property,
    PropertyPhoto,
    PropertyType,
    ServiceTicket,
    State,
    Task,
)

SMALL_RUN = {
    'brokers': 4,
    'owners': 4,
    'clients': 5,
    'condominiums': 2,
    'properties': 6,
    'leads': 8,
    'deals': 10,
    'tickets': 3,
    'tasks': 5,
    'posts': 2,
    'banners': 0,
    'photos': 0,
}


class SeedAgencyDemoTests(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name='Imobiliária Um')

        country = Country.objects.create(name='Brasil', code='BRA')
        state = State.objects.create(country=country, name='Rio de Janeiro', abbreviation='RJ')
        city = City.objects.create(state=state, name='Petrópolis', ibge_code='3303906')

        for name in ['Centro', 'Quitandinha', 'Itaipava']:
            Neighborhood.objects.create(city=city, name=name)

        PropertyType.objects.create(name='Casa')
        PropertyType.objects.create(name='Apartamento')

    def seed(self, **overrides):
        call_command('seedagencydemo', stdout=StringIO(), **{**SMALL_RUN, **overrides})

    def test_cria_o_volume_pedido_em_cada_cadastro(self):
        self.seed()

        self.assertEqual(Broker.objects.count(), 4)
        self.assertEqual(Owner.objects.count(), 4)
        self.assertEqual(Client.objects.count(), 5)
        self.assertEqual(Condominium.objects.count(), 2)
        self.assertEqual(Property.objects.count(), 6)
        self.assertEqual(Lead.objects.count(), 8)
        self.assertEqual(Deal.objects.count(), 10)
        self.assertEqual(ServiceTicket.objects.count(), 3)
        self.assertEqual(Task.objects.count(), 5)

    def test_tudo_pertence_a_imobiliaria_informada(self):
        other = Agency.objects.create(name='Imobiliária Dois')

        self.seed(agency=self.agency.name)

        for model in [Broker, Owner, Client, Condominium, Property, Lead, Deal, ServiceTicket, Task]:
            self.assertEqual(model.objects.filter(agency=other).count(), 0, model.__name__)

    def test_historico_fica_espalhado_no_tempo(self):
        self.seed(properties=12, months=12)

        months = {
            item.created_at.date().replace(day=1) for item in Property.objects.all()
        }
        self.assertGreater(len(months), 1)
        self.assertLessEqual(max(months), timezone.localdate().replace(day=1))

    def test_negocio_encerrado_nao_fecha_no_futuro(self):
        self.seed(deals=40)

        closed = Deal.objects.filter(closed_at__isnull=False)

        self.assertTrue(closed.exists())
        self.assertFalse(closed.filter(closed_at__gt=timezone.localdate()).exists())

    def test_rodar_de_novo_acrescenta_sem_quebrar_o_nome_unico(self):
        self.seed()
        self.seed(seed=99)

        self.assertEqual(Broker.objects.count(), 8)
        self.assertEqual(Owner.objects.count(), 8)
        self.assertEqual(len(set(Broker.objects.values_list('name', flat=True))), 8)

    def test_rodada_parcial_reaproveita_os_cadastros_existentes(self):
        self.seed()

        self.seed(brokers=0, owners=0, clients=0, condominiums=0, properties=0, leads=0,
                  deals=6, tickets=0, tasks=0, posts=0)

        recent = Deal.objects.order_by('-created_at')[:6]
        self.assertEqual(Property.objects.count(), 6)
        self.assertTrue(any(deal.responsible_id for deal in recent))
        self.assertTrue(any(deal.property_code for deal in recent))

    def test_sem_fotos_a_galeria_fica_vazia(self):
        self.seed(photos=0)

        self.assertEqual(PropertyPhoto.objects.count(), 0)

    def test_sem_bairro_cadastrado_o_comando_avisa(self):
        Neighborhood.objects.all().delete()

        with self.assertRaises(CommandError):
            self.seed()
