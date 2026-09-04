"""Testes da ordenação das listagens: campos aceitos, campo recusado e o preço do imóvel."""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import (
    Agency,
    Broker,
    City,
    Client,
    Country,
    Neighborhood,
    Property,
    PropertyPrice,
    PropertyType,
    State,
    User,
    UserPermission,
)
from core.resources import AccessLevel


def grant(user, resource, level):
    UserPermission.objects.update_or_create(
        user=user, resource=resource, defaults={'level': level}
    )


class OrderingTestCase(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name='Imobiliária Um')
        self.user = User.objects.create(
            email='corretor@um.com', agency=self.agency, type=User.Type.USER
        )
        self.user.set_password('senha-de-teste-123')
        self.user.save()

        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.user)

    def codes(self, url, ordering, **params):
        response = self.client_api.get(url, {'ordering': ordering, **params})
        self.assertEqual(response.status_code, 200)

        return [item['code'] for item in response.json()['data']['results']]


class ListOrderingTests(OrderingTestCase):
    def setUp(self):
        super().setUp()
        grant(self.user, 'corretores', AccessLevel.READ)
        grant(self.user, 'clientes', AccessLevel.READ)

        for name, email in [('Carlos', 'c@um.com'), ('Ana', 'a@um.com'), ('Bruno', 'b@um.com')]:
            Broker.objects.create(agency=self.agency, name=name, email=email)

    def names(self, ordering):
        response = self.client_api.get('/brokers/', {'ordering': ordering})
        self.assertEqual(response.status_code, 200)

        return [item['name'] for item in response.json()['data']['results']]

    def test_ordena_crescente_pelo_campo_pedido(self):
        self.assertEqual(self.names('name'), ['Ana', 'Bruno', 'Carlos'])

    def test_o_prefixo_de_menos_inverte_a_ordem(self):
        self.assertEqual(self.names('-name'), ['Carlos', 'Bruno', 'Ana'])

    def test_ordena_por_outra_coluna_da_listagem(self):
        self.assertEqual(self.names('email'), ['Ana', 'Bruno', 'Carlos'])

    def test_campo_fora_da_lista_cai_na_ordem_padrao(self):
        # `agency_id` não está em ordering_fields: aceitar ordenaria por um campo interno.
        self.assertEqual(self.names('agency_id'), ['Ana', 'Bruno', 'Carlos'])

    def test_cliente_ordena_pela_cidade(self):
        country = Country.objects.create(name='Brasil', code='BRA')
        state = State.objects.create(country=country, name='Rio de Janeiro', abbreviation='RJ')
        city = City.objects.create(state=state, name='Niterói', ibge_code='3303302')
        neighborhood = Neighborhood.objects.create(city=city, name='Icaraí')

        Client.objects.create(agency=self.agency, name='Sem cidade')
        Client.objects.create(agency=self.agency, name='Com cidade', neighborhood=neighborhood)

        response = self.client_api.get('/clients/', {'ordering': '-neighborhood__city__name'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['results'][0]['name'], 'Com cidade')


class PropertyPriceOrderingTests(OrderingTestCase):
    def setUp(self):
        super().setUp()
        grant(self.user, 'imoveis', AccessLevel.READ)

        self.type = PropertyType.objects.create(name='Casa')
        self.cheap = self._property('CHEAP', sale=200000, rent=5000)
        self.expensive = self._property('EXPENSIVE', sale=900000, rent=1000)
        self.rent_only = self._property('RENTONLY', rent=3000)

    def _property(self, code, sale=None, rent=None):
        instance = Property.objects.create(
            agency=self.agency, code=code, name=code, type=self.type
        )

        if sale is not None:
            PropertyPrice.objects.create(
                property=instance, purpose=PropertyPrice.Purpose.SALE, amount=Decimal(sale)
            )

        if rent is not None:
            PropertyPrice.objects.create(
                property=instance, purpose=PropertyPrice.Purpose.RENT, amount=Decimal(rent)
            )

        return instance

    def test_sem_finalidade_filtrada_vale_a_venda_e_a_locacao_completa(self):
        # Sem venda cadastrada, o imóvel entra na ordenação pelo valor de locação.
        self.assertEqual(
            self.codes('/properties/', 'price'), ['RENTONLY', 'CHEAP', 'EXPENSIVE']
        )

    def test_maior_preco_inverte_a_ordem(self):
        self.assertEqual(
            self.codes('/properties/', '-price'), ['EXPENSIVE', 'CHEAP', 'RENTONLY']
        )

    def test_finalidade_filtrada_manda_no_valor_da_ordenacao(self):
        # Filtrando locação, o caro na venda passa a ser o barato na ordenação.
        self.assertEqual(
            self.codes('/properties/', 'price', purpose='RENT'),
            ['EXPENSIVE', 'RENTONLY', 'CHEAP'],
        )

    def test_imovel_sem_preco_fica_no_fim_nas_duas_direcoes(self):
        Property.objects.create(agency=self.agency, code='NOPRICE', name='NOPRICE', type=self.type)

        self.assertEqual(self.codes('/properties/', 'price')[-1], 'NOPRICE')
        self.assertEqual(self.codes('/properties/', '-price')[-1], 'NOPRICE')

    def test_imovel_de_outra_imobiliaria_nao_entra_na_ordenacao(self):
        other = Agency.objects.create(name='Imobiliária Dois')
        outra = Property.objects.create(agency=other, code='OUTRA', name='OUTRA')
        PropertyPrice.objects.create(
            property=outra, purpose=PropertyPrice.Purpose.SALE, amount=Decimal(1)
        )

        self.assertNotIn('OUTRA', self.codes('/properties/', 'price'))

    def test_ordem_padrao_continua_pelos_mais_recentes(self):
        response = self.client_api.get('/properties/')

        codes = [item['code'] for item in response.json()['data']['results']]
        self.assertEqual(codes, ['RENTONLY', 'EXPENSIVE', 'CHEAP'])
