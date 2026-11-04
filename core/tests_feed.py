"""Testes do feed XML dos portais: chave, escopo (marcados ou todos), isolamento e conteúdo."""

from xml.etree import ElementTree

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import (
    Agency,
    AgencyExporter,
    AgencyExporterPlan,
    City,
    Country,
    Exporter,
    Fee,
    Neighborhood,
    Property,
    PropertyExporter,
    PropertyFee,
    PropertyPrice,
    PropertyType,
    State,
    User,
)
from core.services import grant_full_access
from core.services.property_feed import feed_key

NAMESPACE = {'vr': 'http://www.vivareal.com/schemas/1.0/VRSync'}


class PropertyFeedTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(
            name='Imobiliária Feed', email='contato@feed.com', phone='24999990000'
        )
        self.other_agency = Agency.objects.create(name='Outra Imobiliária')

        # A migration do catálogo já cria os portais padrão no banco de teste.
        self.exporter = Exporter.objects.get(name='ZAP Imóveis')
        self.plan = self.exporter.plans.get(name='Destaque')
        self.other_exporter = Exporter.objects.get(name='OLX')

        agency_exporter = AgencyExporter.objects.create(agency=self.agency, exporter=self.exporter)
        AgencyExporterPlan.objects.create(agency_exporter=agency_exporter, plan=self.plan, limit=10)

        country = Country.objects.create(name='Brasil', code='BR')
        state = State.objects.create(country=country, name='Rio de Janeiro', abbreviation='RJ')
        city = City.objects.create(state=state, name='Petrópolis', ibge_code='3303906')
        self.neighborhood = Neighborhood.objects.create(city=city, name='Itaipava')
        self.house = PropertyType.objects.create(name='Casa')

        self.marked = self.create_property('100', 'Casa marcada')
        PropertyExporter.objects.create(property=self.marked, exporter=self.exporter, plan=self.plan)
        PropertyPrice.objects.create(property=self.marked, purpose='SALE', amount=900000)
        PropertyPrice.objects.create(property=self.marked, purpose='RENT', amount=4500)
        PropertyFee.objects.create(
            property=self.marked, fee=Fee.objects.get_or_create(name='Condomínio')[0], amount=350
        )

        self.unmarked = self.create_property('101', 'Casa sem portal')
        self.inactive = self.create_property('102', 'Casa inativa', is_active=False)
        self.create_property('103', 'Casa de outra imobiliária', agency=self.other_agency)

        self.key = feed_key(self.agency)

    def create_property(self, code, name, agency=None, **fields):
        return Property.objects.create(
            agency=agency or self.agency,
            code=code,
            name=name,
            type=self.house,
            neighborhood=self.neighborhood,
            address='Estrada União e Indústria',
            number='1000',
            bedrooms=3,
            **fields,
        )

    def feed_url(self, route_name='property_feed', **overrides):
        kwargs = {
            'agency_slug': self.agency.slug,
            'key': self.key,
            'exporter_slug': self.exporter.slug,
        }
        kwargs.update(overrides)

        return reverse(route_name, kwargs=kwargs)

    def listing_ids(self, response):
        root = ElementTree.fromstring(response.content)

        return [element.text for element in root.findall('.//vr:ListingID', NAMESPACE)]

    def test_feed_marcados_traz_so_os_imoveis_marcados_para_o_portal(self):
        response = self.client.get(self.feed_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response['Content-Type'].startswith('application/xml'))
        self.assertEqual(self.listing_ids(response), ['100'])

    def test_feed_completo_traz_todos_os_imoveis_ativos_da_imobiliaria(self):
        response = self.client.get(self.feed_url('property_feed_all'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # O inativo e o de outra imobiliária ficam de fora mesmo no feed completo.
        self.assertEqual(self.listing_ids(response), ['100', '101'])

    def test_feed_e_publico_e_nao_exige_token(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer token-invalido')

        response = self.client.get(self.feed_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_chave_errada_responde_404(self):
        response = self.client.get(self.feed_url(key='0' * 24))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_portal_nao_ativado_pela_imobiliaria_responde_404(self):
        response = self.client.get(self.feed_url(exporter_slug=self.other_exporter.slug))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_imobiliaria_inativa_responde_404(self):
        self.agency.delete()

        response = self.client.get(self.feed_url())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_chave_de_uma_imobiliaria_nao_abre_o_feed_de_outra(self):
        AgencyExporter.objects.create(agency=self.other_agency, exporter=self.exporter)

        response = self.client.get(self.feed_url(agency_slug=self.other_agency.slug))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_anuncio_leva_precos_taxas_endereco_e_contato(self):
        response = self.client.get(self.feed_url())
        root = ElementTree.fromstring(response.content)
        listing = root.find('.//vr:Listing', NAMESPACE)

        def text(path):
            element = listing.find(path, NAMESPACE)

            return element.text if element is not None else None

        self.assertEqual(text('vr:TransactionType'), 'Sale/Rent')
        self.assertEqual(text('vr:Details/vr:PropertyType'), 'Residential / Home')
        self.assertEqual(text('vr:Details/vr:ListPrice'), '900000')
        self.assertEqual(text('vr:Details/vr:RentalPrice'), '4500')
        self.assertEqual(text('vr:Details/vr:PropertyAdministrationFee'), '350')
        self.assertEqual(text('vr:Details/vr:Bedrooms'), '3')
        self.assertEqual(text('vr:Location/vr:City'), 'Petrópolis')
        self.assertEqual(text('vr:Location/vr:Neighborhood'), 'Itaipava')
        self.assertEqual(text('vr:Location/vr:StreetNumber'), '1000')
        self.assertEqual(text('vr:ContactInfo/vr:Email'), 'contato@feed.com')
        self.assertEqual(root.find('vr:Header/vr:Provider', NAMESPACE).text, 'Imobiliária Feed')

    def test_tipo_do_imovel_vira_categoria_do_portal(self):
        self.marked.type = PropertyType.objects.create(name='Lote/Terreno')
        self.marked.save()

        response = self.client.get(self.feed_url())
        root = ElementTree.fromstring(response.content)

        self.assertEqual(
            root.find('.//vr:Details/vr:PropertyType', NAMESPACE).text, 'Residential / Land Lot'
        )

    def test_preco_oculto_nao_vai_para_o_portal(self):
        PropertyPrice.objects.filter(property=self.marked, purpose='SALE').update(show_price=False)

        response = self.client.get(self.feed_url())
        root = ElementTree.fromstring(response.content)
        listing = root.find('.//vr:Listing', NAMESPACE)

        self.assertIsNone(listing.find('vr:Details/vr:ListPrice', NAMESPACE))
        self.assertEqual(listing.find('vr:TransactionType', NAMESPACE).text, 'For Rent')

    def test_configuracao_do_portal_devolve_os_dois_links(self):
        user = User.objects.create(email='user@feed.com', agency=self.agency, type=User.Type.USER)
        grant_full_access(user)
        self.client.force_authenticate(user)

        response = self.client.get('/agency-exporters/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        record = response.json()['data']['results'][0]
        self.assertTrue(record['feed_url'].endswith(self.feed_url()))
        self.assertTrue(record['feed_url_all'].endswith(self.feed_url('property_feed_all')))
        self.assertTrue(record['feed_url'].startswith('http://testserver/'))
