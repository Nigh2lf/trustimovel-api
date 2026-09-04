"""Testes do endpoint de relatórios: acesso, período, isolamento e os números agregados."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    Agency,
    Broker,
    Deal,
    Lead,
    Property,
    PropertyPrice,
    PropertyType,
    User,
    UserPermission,
)
from core.resources import AccessLevel


def grant(user, resource, level):
    UserPermission.objects.update_or_create(
        user=user, resource=resource, defaults={'level': level}
    )


class ReportsTestCase(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name='Imobiliária Um')
        self.other_agency = Agency.objects.create(name='Imobiliária Dois')

        self.user = User.objects.create(
            email='corretor@um.com', agency=self.agency, type=User.Type.USER
        )
        self.user.set_password('senha-de-teste-123')
        self.user.save()

        self.broker = Broker.objects.create(agency=self.agency, name='Maria Santos')

        self.today = timezone.localdate()
        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.user)

    def report(self, **params):
        response = self.client_api.get('/reports/', params)
        self.assertEqual(response.status_code, 200)

        return response.json()['data']

    def won_deal(self, value, closed_at, agency=None, responsible=None, stage=None):
        return Deal.objects.create(
            agency=agency or self.agency,
            title='Negócio ganho',
            client_name='Cliente',
            value=value,
            stage=stage or Deal.Stage.CLOSING,
            outcome=Deal.Outcome.WON,
            closed_at=closed_at,
            responsible=responsible,
        )


class ReportsAccessTests(ReportsTestCase):
    def test_sem_autenticacao_devolve_401(self):
        self.assertEqual(APIClient().get('/reports/').status_code, 401)

    def test_sem_permissao_devolve_403(self):
        self.assertEqual(self.client_api.get('/reports/').status_code, 403)

    def test_leitura_libera_o_relatorio(self):
        grant(self.user, 'relatorios', AccessLevel.READ)

        self.assertEqual(self.client_api.get('/reports/').status_code, 200)


class ReportsPeriodTests(ReportsTestCase):
    def setUp(self):
        super().setUp()
        grant(self.user, 'relatorios', AccessLevel.READ)

    def test_periodo_padrao_cobre_seis_meses(self):
        period = self.report()['period']

        self.assertEqual(period['end'], self.today.isoformat())
        self.assertEqual(len(self.report()['sales']['monthly']), 6)

    def test_data_em_formato_invalido_devolve_400(self):
        response = self.client_api.get('/reports/', {'start': '01/01/2026'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['status'], 'error')
        self.assertEqual(response.json()['errors'][0]['field'], 'start')

    def test_data_inicial_depois_da_final_devolve_400(self):
        response = self.client_api.get(
            '/reports/', {'start': '2026-05-01', 'end': '2026-04-01'}
        )

        self.assertEqual(response.status_code, 400)

    def test_periodo_maior_que_cinco_anos_devolve_400(self):
        response = self.client_api.get(
            '/reports/', {'start': '2015-01-01', 'end': self.today.isoformat()}
        )

        self.assertEqual(response.status_code, 400)


class ReportsNumbersTests(ReportsTestCase):
    def setUp(self):
        super().setUp()
        grant(self.user, 'relatorios', AccessLevel.READ)

    def test_vendas_somam_apenas_negocios_ganhos_da_propria_imobiliaria(self):
        self.won_deal(100000, self.today)
        self.won_deal(50000, self.today)
        self.won_deal(999999, self.today, agency=self.other_agency)
        Deal.objects.create(
            agency=self.agency,
            title='Perdido',
            client_name='Cliente',
            value=300000,
            outcome=Deal.Outcome.LOST,
            loss_reason=Deal.LossReason.PRICE,
            closed_at=self.today,
        )

        summary = self.report()['summary']['current']

        self.assertEqual(summary['total_count'], 2)
        self.assertEqual(summary['total_value'], 150000.0)
        self.assertEqual(summary['average_ticket'], 75000.0)
        self.assertEqual(summary['conversion_rate'], 66.7)

    def test_negocio_ganho_fora_do_periodo_fica_de_fora(self):
        self.won_deal(100000, self.today - timedelta(days=400))

        self.assertEqual(self.report()['summary']['current']['total_count'], 0)

    def test_negocio_excluido_nao_entra_na_soma(self):
        self.won_deal(100000, self.today).delete()

        self.assertEqual(self.report()['summary']['current']['total_count'], 0)

    def test_serie_mensal_traz_o_mes_do_fechamento(self):
        self.won_deal(80000, self.today)

        monthly = self.report()['sales']['monthly']

        self.assertEqual(monthly[-1]['month'], self.today.replace(day=1).isoformat())
        self.assertEqual(monthly[-1]['value'], 80000.0)
        self.assertEqual(monthly[-1]['count'], 1)

    def test_variacao_compara_com_o_periodo_anterior(self):
        self.won_deal(200000, self.today)
        self.won_deal(100000, self.today - timedelta(days=150))

        summary = self.report(
            start=(self.today - timedelta(days=99)).isoformat(), end=self.today.isoformat()
        )['summary']

        self.assertEqual(summary['previous']['total_value'], 100000.0)
        self.assertEqual(summary['changes']['total_value'], 100.0)

    def test_variacao_sem_base_de_comparacao_vem_nula(self):
        self.won_deal(200000, self.today)

        self.assertIsNone(self.report()['summary']['changes']['total_value'])

    def test_imoveis_agrupam_por_tipo_com_o_preco_de_venda(self):
        house = PropertyType.objects.create(name='Casa')
        apartment = PropertyType.objects.create(name='Apartamento')
        first = Property.objects.create(agency=self.agency, name='Casa 1', type=house)
        Property.objects.create(agency=self.agency, name='Casa 2', type=house, is_active=False)
        Property.objects.create(agency=self.agency, name='Apto', type=apartment)
        Property.objects.create(agency=self.other_agency, name='De outra', type=house)
        PropertyPrice.objects.create(
            property=first, purpose=PropertyPrice.Purpose.SALE, amount=400000
        )

        properties = self.report()['properties']
        by_type = {row['name']: row for row in properties['by_type']}

        self.assertEqual(properties['total'], 3)
        self.assertEqual(properties['active'], 2)
        self.assertEqual(properties['inactive'], 1)
        self.assertEqual(by_type['Casa']['count'], 2)
        self.assertEqual(by_type['Casa']['value'], 400000.0)
        self.assertEqual(by_type['Casa']['average'], 400000.0)
        self.assertEqual(by_type['Apartamento']['value'], 0.0)

    def test_leads_contam_por_origem_e_por_situacao(self):
        Lead.objects.create(agency=self.agency, name='Um', source=Lead.Source.SITE)
        Lead.objects.create(
            agency=self.agency,
            name='Dois',
            source=Lead.Source.SITE,
            status=Lead.Status.CONVERTED,
        )
        Lead.objects.create(agency=self.other_agency, name='De outra')

        leads = self.report()['leads']
        by_source = {row['value']: row['count'] for row in leads['by_source']}

        self.assertEqual(leads['total'], 2)
        self.assertEqual(leads['converted'], 1)
        self.assertEqual(leads['conversion_rate'], 50.0)
        self.assertEqual(by_source['SITE'], 2)
        self.assertEqual(by_source['WHATSAPP'], 0)

    def test_corretores_trazem_ganhos_abertos_e_leads(self):
        self.won_deal(300000, self.today, responsible=self.broker)
        Deal.objects.create(
            agency=self.agency,
            title='Em aberto',
            client_name='Cliente',
            value=50000,
            responsible=self.broker,
        )
        Lead.objects.create(agency=self.agency, name='Lead', responsible=self.broker)

        brokers = self.report()['brokers']

        self.assertEqual(len(brokers), 1)
        self.assertEqual(brokers[0]['name'], 'Maria Santos')
        self.assertEqual(brokers[0]['won_count'], 1)
        self.assertEqual(brokers[0]['won_value'], 300000.0)
        self.assertEqual(brokers[0]['open_count'], 1)
        self.assertEqual(brokers[0]['open_value'], 50000.0)
        self.assertEqual(brokers[0]['leads_count'], 1)

    def test_negocio_sem_responsavel_aparece_agrupado(self):
        self.won_deal(100000, self.today)

        self.assertEqual(self.report()['brokers'][0]['name'], 'Sem responsável')

    def test_funil_acumula_os_estagios_seguintes(self):
        Deal.objects.create(
            agency=self.agency,
            title='Qualificação',
            client_name='A',
            value=1000,
            stage=Deal.Stage.QUALIFICATION,
        )
        Deal.objects.create(
            agency=self.agency,
            title='Proposta',
            client_name='B',
            value=2000,
            stage=Deal.Stage.PROPOSAL,
        )
        Deal.objects.create(
            agency=self.other_agency, title='De outra', client_name='C', value=9000
        )

        funnel = self.report()['funnel']
        stages = {row['stage']: row for row in funnel['stages']}

        self.assertEqual(funnel['total'], 2)
        self.assertEqual(stages['QUALIFICATION']['count'], 2)
        self.assertEqual(stages['QUALIFICATION']['conversion'], 100.0)
        self.assertEqual(stages['PROPOSAL']['count'], 1)
        self.assertEqual(stages['PROPOSAL']['conversion'], 50.0)
        self.assertEqual(stages['CLOSING']['count'], 0)

    def test_funil_traz_desfechos_e_motivos_de_perda(self):
        self.won_deal(10000, self.today)
        Deal.objects.create(
            agency=self.agency,
            title='Perdido',
            client_name='B',
            value=5000,
            outcome=Deal.Outcome.LOST,
            loss_reason=Deal.LossReason.PRICE,
            closed_at=self.today,
        )

        funnel = self.report()['funnel']

        self.assertEqual(funnel['outcomes']['won']['count'], 1)
        self.assertEqual(funnel['outcomes']['won']['value'], 10000.0)
        self.assertEqual(funnel['outcomes']['lost']['count'], 1)
        self.assertEqual(funnel['outcomes']['conversion_rate'], 50.0)
        self.assertEqual(funnel['loss_reasons'][0]['label'], 'Preço')

    def test_usuario_sem_imobiliaria_recebe_relatorio_vazio(self):
        admin = User.objects.create(email='admin@plataforma.com', type=User.Type.ADMIN)
        self.won_deal(100000, self.today)
        self.client_api.force_authenticate(user=admin)

        data = self.report()

        self.assertEqual(data['summary']['current']['total_count'], 0)
        self.assertEqual(data['properties']['total'], 0)
        self.assertEqual(data['brokers'], [])
