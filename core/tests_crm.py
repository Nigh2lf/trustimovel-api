"""Testes dos endpoints do CRM: acesso, isolamento por imobiliária e regras de negócio."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Agency, Broker, Deal, Lead, ServiceTicket, Task, User, UserPermission
from core.resources import AccessLevel


def grant(user, resource, level):
    UserPermission.objects.update_or_create(
        user=user, resource=resource, defaults={'level': level}
    )


class CRMTestCase(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name='Imobiliária Um')
        self.other_agency = Agency.objects.create(name='Imobiliária Dois')

        self.user = User.objects.create(
            email='corretor@um.com', agency=self.agency, type=User.Type.USER
        )
        self.user.set_password('senha-de-teste-123')
        self.user.save()

        self.broker = Broker.objects.create(agency=self.agency, name='Maria Santos')
        self.other_broker = Broker.objects.create(agency=self.other_agency, name='De Outra')

        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.user)


class CRMAccessTests(CRMTestCase):
    ENDPOINTS = ['/leads/', '/service-tickets/', '/tasks/', '/deals/']

    def test_sem_autenticacao_devolve_401(self):
        for endpoint in self.ENDPOINTS:
            self.assertEqual(APIClient().get(endpoint).status_code, 401, endpoint)

    def test_sem_permissao_devolve_403(self):
        for endpoint in self.ENDPOINTS:
            self.assertEqual(self.client_api.get(endpoint).status_code, 403, endpoint)

    def test_leitura_lista(self):
        # Concede tudo antes: o mapa de permissões é cacheado por requisição na instância.
        for resource in ['leads', 'atendimentos', 'tarefas', 'funil']:
            grant(self.user, resource, AccessLevel.READ)

        for endpoint in self.ENDPOINTS:
            self.assertEqual(self.client_api.get(endpoint).status_code, 200, endpoint)


class LeadTests(CRMTestCase):
    def setUp(self):
        super().setUp()
        grant(self.user, 'leads', AccessLevel.FULL)

    def test_criacao_gera_codigo_sequencial(self):
        for expected in ['LEAD001', 'LEAD002']:
            response = self.client_api.post(
                '/leads/',
                {'name': f'Lead {expected}', 'responsible': str(self.broker.id)},
                format='json',
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()['data']['code'], expected)

    def test_nao_lista_lead_de_outra_imobiliaria(self):
        Lead.objects.create(agency=self.other_agency, name='De outra')
        Lead.objects.create(agency=self.agency, name='Meu lead')

        response = self.client_api.get('/leads/')

        results = response.json()['data']['results']
        self.assertEqual([item['name'] for item in results], ['Meu lead'])

    def test_recusa_corretor_de_outra_imobiliaria(self):
        response = self.client_api.post(
            '/leads/',
            {'name': 'Lead', 'responsible': str(self.other_broker.id)},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_interacao_registra_e_atualiza_ultimo_contato(self):
        lead = Lead.objects.create(agency=self.agency, name='Lead')

        response = self.client_api.post(
            f'/leads/{lead.id}/interactions/', {'text': 'Liguei para o cliente.'}, format='json'
        )

        self.assertEqual(response.status_code, 201)
        lead.refresh_from_db()
        self.assertEqual(lead.interactions.count(), 1)
        self.assertEqual(lead.last_contact_at, timezone.localdate())

    def test_conversao_cria_negocio_e_marca_o_lead(self):
        grant(self.user, 'funil', AccessLevel.WRITE)
        lead = Lead.objects.create(
            agency=self.agency,
            name='Lead',
            interest=Lead.Interest.RENT,
            responsible=self.broker,
        )

        response = self.client_api.post(f'/leads/{lead.id}/convert/')

        self.assertEqual(response.status_code, 201)
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.CONVERTED)

        deal = Deal.objects.get(lead=lead)
        self.assertEqual(deal.agency_id, self.agency.id)
        self.assertEqual(deal.type, Deal.Type.RENT)
        self.assertEqual(deal.responsible, self.broker)

        # Converter de novo é recusado.
        self.assertEqual(self.client_api.post(f'/leads/{lead.id}/convert/').status_code, 400)

    def test_conversao_exige_permissao_no_funil(self):
        lead = Lead.objects.create(agency=self.agency, name='Lead')

        response = self.client_api.post(f'/leads/{lead.id}/convert/')

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Deal.objects.exists())


class ServiceTicketTests(CRMTestCase):
    def setUp(self):
        super().setUp()
        grant(self.user, 'atendimentos', AccessLevel.FULL)

    def test_criacao_gera_protocolo_do_ano(self):
        response = self.client_api.post(
            '/service-tickets/',
            {'client_name': 'João', 'subject': 'Interesse no AP0012'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        year = timezone.localdate().year
        self.assertEqual(response.json()['data']['protocol'], f'ATD-{year}-001')

    def test_mensagem_entra_na_timeline_e_atualiza_o_ticket(self):
        ticket = ServiceTicket.objects.create(
            agency=self.agency, client_name='João', subject='Visita'
        )

        response = self.client_api.post(
            f'/service-tickets/{ticket.id}/messages/', {'message': 'Olá!'}, format='json'
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(ticket.messages.count(), 1)
        self.assertEqual(ticket.messages.first().author_name, 'corretor@um.com')

    def test_nao_acessa_ticket_de_outra_imobiliaria(self):
        ticket = ServiceTicket.objects.create(
            agency=self.other_agency, client_name='X', subject='Y'
        )

        self.assertEqual(self.client_api.get(f'/service-tickets/{ticket.id}/').status_code, 404)


class TaskTests(CRMTestCase):
    def setUp(self):
        super().setUp()
        grant(self.user, 'tarefas', AccessLevel.FULL)

    def test_visita_exige_imovel(self):
        payload = {
            'title': 'Visita',
            'type': Task.Type.VISIT,
            'due_date': str(timezone.localdate()),
        }

        response = self.client_api.post('/tasks/', payload, format='json')
        self.assertEqual(response.status_code, 400)

        payload['property_code'] = 'AP0012'
        response = self.client_api.post('/tasks/', payload, format='json')
        self.assertEqual(response.status_code, 201)

    def test_atraso_e_calculado(self):
        Task.objects.create(
            agency=self.agency,
            title='Atrasada',
            due_date=timezone.localdate() - timedelta(days=1),
        )
        Task.objects.create(
            agency=self.agency,
            title='Futura',
            due_date=timezone.localdate() + timedelta(days=1),
        )

        results = self.client_api.get('/tasks/').json()['data']['results']
        by_title = {item['title']: item['is_overdue'] for item in results}

        self.assertTrue(by_title['Atrasada'])
        self.assertFalse(by_title['Futura'])

    def test_recusa_lead_de_outra_imobiliaria(self):
        lead = Lead.objects.create(agency=self.other_agency, name='De outra')

        response = self.client_api.post(
            '/tasks/',
            {'title': 'Ligar', 'due_date': str(timezone.localdate()), 'lead': str(lead.id)},
            format='json',
        )

        self.assertEqual(response.status_code, 400)


class DealTests(CRMTestCase):
    def setUp(self):
        super().setUp()
        grant(self.user, 'funil', AccessLevel.FULL)
        self.deal = Deal.objects.create(
            agency=self.agency, title='Apartamento Leblon', client_name='João', value=500000
        )

    def test_perda_exige_motivo(self):
        response = self.client_api.patch(
            f'/deals/{self.deal.id}/', {'outcome': Deal.Outcome.LOST}, format='json'
        )
        self.assertEqual(response.status_code, 400)

        response = self.client_api.patch(
            f'/deals/{self.deal.id}/',
            {'outcome': Deal.Outcome.LOST, 'loss_reason': Deal.LossReason.PRICE},
            format='json',
        )
        self.assertEqual(response.status_code, 200)

        self.deal.refresh_from_db()
        self.assertEqual(self.deal.closed_at, timezone.localdate())

    def test_reabrir_limpa_o_desfecho(self):
        self.deal.outcome = Deal.Outcome.LOST
        self.deal.loss_reason = Deal.LossReason.PRICE
        self.deal.closed_at = timezone.localdate()
        self.deal.save()

        response = self.client_api.patch(
            f'/deals/{self.deal.id}/', {'outcome': None}, format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.deal.refresh_from_db()
        self.assertIsNone(self.deal.outcome)
        self.assertEqual(self.deal.loss_reason, '')
        self.assertIsNone(self.deal.closed_at)

    def test_probabilidade_fora_da_faixa_falha(self):
        response = self.client_api.patch(
            f'/deals/{self.deal.id}/', {'probability': 150}, format='json'
        )

        self.assertEqual(response.status_code, 400)


class DashboardCRMTests(CRMTestCase):
    def setUp(self):
        super().setUp()
        grant(self.user, 'dashboard', AccessLevel.READ)

    def test_resumo_traz_o_bloco_do_crm(self):
        Lead.objects.create(agency=self.agency, name='Novo lead')
        Lead.objects.create(agency=self.other_agency, name='De outra')
        Deal.objects.create(agency=self.agency, title='Ativo', client_name='A', value=1000)
        Deal.objects.create(
            agency=self.agency,
            title='Ganho',
            client_name='B',
            value=2000,
            outcome=Deal.Outcome.WON,
        )
        Task.objects.create(agency=self.agency, title='Hoje', due_date=timezone.localdate())
        ServiceTicket.objects.create(agency=self.agency, client_name='C', subject='Aberto')

        crm = self.client_api.get('/dashboard/').json()['data']['crm']

        self.assertEqual(crm['leads'], {'total': 1, 'new': 1})
        self.assertEqual(crm['deals']['active'], 1)
        self.assertEqual(crm['deals']['total_value'], 1000.0)
        self.assertEqual(crm['tasks']['today'], 1)
        self.assertEqual(crm['tasks']['today_items'][0]['title'], 'Hoje')
        self.assertEqual(crm['tickets']['open'], 1)
