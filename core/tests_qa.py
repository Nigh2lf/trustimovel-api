"""Testes das correções da auditoria de QA: resumos e filtros do CRM, validações e limite do plano."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    Agency,
    AgencySettings,
    Broker,
    Client,
    Deal,
    Lead,
    Owner,
    Plan,
    Property,
    PropertyType,
    Task,
    User,
    UserPermission,
)
from core.resources import AccessLevel


def grant(user, resource, level):
    UserPermission.objects.update_or_create(user=user, resource=resource, defaults={'level': level})


class QATestCase(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name='Imobiliária Um')
        self.other_agency = Agency.objects.create(name='Imobiliária Dois')
        self.user = User.objects.create(email='gestor@um.com', agency=self.agency, type=User.Type.USER)
        self.broker = Broker.objects.create(agency=self.agency, name='Maria Santos')

        for resource in ('leads', 'funil', 'tarefas', 'atendimentos', 'imoveis', 'clientes', 'proprietarios', 'dashboard', 'configuracoes'):
            grant(self.user, resource, AccessLevel.FULL)

        self.api = APIClient()
        self.api.force_authenticate(user=self.user)


class CrmPaginationAndSummaryTests(QATestCase):
    def test_leads_paginam_de_quinze_em_quinze_e_o_resumo_conta_o_total(self):
        for index in range(20):
            Lead.objects.create(agency=self.agency, name=f'Lead {index}', phone='(21) 99999-0000',
                                status=Lead.Status.QUALIFIED if index < 5 else Lead.Status.NEW)
        Lead.objects.create(agency=self.other_agency, name='De outra', phone='(21) 99999-0000')

        page = self.api.get('/leads/').json()['data']
        self.assertEqual(page['count'], 20)
        self.assertEqual(len(page['results']), 15)
        self.assertIsNotNone(page['next'])

        summary = self.api.get('/leads/summary/').json()['data']
        self.assertEqual(summary['total'], 20)
        self.assertEqual(summary['qualified'], 5)
        self.assertEqual(summary['new'], 15)

    def test_resumo_de_leads_respeita_os_filtros_da_lista(self):
        Lead.objects.create(agency=self.agency, name='Ana', phone='(21) 99999-0000', source=Lead.Source.SITE)
        Lead.objects.create(agency=self.agency, name='Bia', phone='(21) 99999-0000', source=Lead.Source.PHONE)

        summary = self.api.get('/leads/summary/', {'source': 'PHONE'}).json()['data']
        self.assertEqual(summary['total'], 1)

    def test_page_size_maior_segue_o_teto(self):
        for index in range(30):
            Lead.objects.create(agency=self.agency, name=f'Lead {index}', phone='(21) 99999-0000')

        page = self.api.get('/leads/', {'page_size': 200}).json()['data']
        self.assertEqual(len(page['results']), 30)

    def test_funil_filtra_abertos_e_resume_o_conjunto_inteiro(self):
        for index in range(3):
            Deal.objects.create(agency=self.agency, title=f'Aberto {index}', client_name='C',
                                value=100, probability=50, responsible=self.broker)
        Deal.objects.create(agency=self.agency, title='Ganho', client_name='C', value=500,
                            outcome=Deal.Outcome.WON, responsible=self.broker)
        Deal.objects.create(agency=self.agency, title='Perdido', client_name='C', value=700,
                            outcome=Deal.Outcome.LOST, loss_reason=Deal.LossReason.PRICE,
                            responsible=self.broker)

        open_deals = self.api.get('/deals/', {'is_open': 'true'}).json()['data']
        self.assertEqual(open_deals['count'], 3)

        closed = self.api.get('/deals/', {'is_open': 'false'}).json()['data']
        self.assertEqual(closed['count'], 2)

        summary = self.api.get('/deals/summary/').json()['data']
        self.assertEqual(summary['active'], 3)
        self.assertEqual(summary['total_value'], 300.0)
        self.assertEqual(summary['weighted_value'], 150.0)
        self.assertEqual(summary['won'], 1)
        self.assertEqual(summary['lost'], 1)
        self.assertEqual(summary['conversion_rate'], 50)

    def test_tarefas_filtram_atrasadas_e_periodo_e_resumem(self):
        today = timezone.localdate()
        Task.objects.create(agency=self.agency, title='Atrasada', responsible=self.broker,
                            due_date=today - timedelta(days=2))
        Task.objects.create(agency=self.agency, title='Concluída antiga', responsible=self.broker,
                            due_date=today - timedelta(days=2), status=Task.Status.DONE)
        Task.objects.create(agency=self.agency, title='Futura', responsible=self.broker,
                            due_date=today + timedelta(days=10))

        overdue = self.api.get('/tasks/', {'overdue': 'true'}).json()['data']
        self.assertEqual([item['title'] for item in overdue['results']], ['Atrasada'])

        window = self.api.get('/tasks/', {
            'due_date_from': (today + timedelta(days=1)).isoformat(),
            'due_date_to': (today + timedelta(days=30)).isoformat(),
        }).json()['data']
        self.assertEqual([item['title'] for item in window['results']], ['Futura'])

        summary = self.api.get('/tasks/summary/').json()['data']
        self.assertEqual(summary, {'total': 3, 'pending': 2, 'done': 1, 'overdue': 1})

    def test_resumo_de_atendimentos(self):
        from core.models import ServiceTicket

        ServiceTicket.objects.create(agency=self.agency, client_name='A', subject='S',
                                     priority=ServiceTicket.Priority.URGENT)
        ServiceTicket.objects.create(agency=self.agency, client_name='B', subject='S',
                                     status=ServiceTicket.Status.RESOLVED)

        summary = self.api.get('/service-tickets/summary/').json()['data']
        self.assertEqual(summary, {'total': 2, 'open': 1, 'resolved': 1, 'urgent': 1})

    def test_resumo_nao_mistura_imobiliarias(self):
        Task.objects.create(agency=self.other_agency, title='De outra', due_date=timezone.localdate())

        summary = self.api.get('/tasks/summary/').json()['data']
        self.assertEqual(summary['total'], 0)

    def test_resumo_sem_autenticacao_e_sem_permissao(self):
        self.assertEqual(APIClient().get('/leads/summary/').status_code, 401)

        outsider = User.objects.create(email='sem@um.com', agency=self.agency, type=User.Type.USER)
        api = APIClient()
        api.force_authenticate(user=outsider)
        self.assertEqual(api.get('/leads/summary/').status_code, 403)


class CrmValidationTests(QATestCase):
    def test_lead_sem_email_pode_ser_editado(self):
        lead = Lead.objects.create(agency=self.agency, name='Da fila', phone='(21) 99999-0000')

        response = self.api.patch(f'/leads/{lead.id}/', {'status': 'IN_CONTACT'}, format='json')

        self.assertEqual(response.status_code, 200, response.content)

    def test_lead_precisa_de_telefone_ou_email(self):
        response = self.api.post('/leads/', {'name': 'Sem contato', 'source': 'SITE', 'interest': 'PURCHASE'}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('phone', response.json()['error'])

    def test_lead_recusa_telefone_curto_com_mensagem_legivel(self):
        response = self.api.post(
            '/leads/',
            {'name': 'Ana', 'phone': '(12) 3', 'source': 'SITE', 'interest': 'PURCHASE'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('DDD', response.json()['error']['phone'][0])

    def test_erros_de_escolha_saem_em_portugues_e_todos_de_uma_vez(self):
        response = self.api.post('/leads/', {'name': 'Ana', 'phone': '(21) 99999-0000', 'source': '', 'interest': ''}, format='json')

        errors = response.json()['error']
        self.assertEqual(response.status_code, 400)
        self.assertEqual(errors['source'], ['Selecione a origem.'])
        self.assertEqual(errors['interest'], ['Selecione o interesse.'])

    def test_negocio_e_tarefa_exigem_responsavel(self):
        deal = self.api.post(
            '/deals/',
            {'title': 'Venda', 'client_name': 'C', 'value': 10, 'stage': 'QUALIFICATION', 'probability': 10},
            format='json',
        )
        self.assertEqual(deal.status_code, 400)
        self.assertEqual(deal.json()['error']['responsible'], ['Selecione o responsável.'])

        task = self.api.post(
            '/tasks/',
            {'title': 'Ligar', 'type': 'CALL', 'due_date': timezone.localdate().isoformat(), 'responsible': None},
            format='json',
        )
        self.assertEqual(task.status_code, 400)
        self.assertIn('responsible', task.json()['error'])

    def test_mover_negocio_no_quadro_nao_exige_reenviar_o_responsavel(self):
        deal = Deal.objects.create(agency=self.agency, title='Venda', client_name='C', responsible=self.broker)

        response = self.api.patch(f'/deals/{deal.id}/', {'stage': 'PROPOSAL'}, format='json')

        self.assertEqual(response.status_code, 200, response.content)


class PeopleValidationTests(QATestCase):
    def test_cpf_invalido_e_recusado(self):
        response = self.api.post(
            '/clients/', {'name': 'Zero', 'phone': '(21) 99999-0000', 'document': '000.000.000-00'}, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('document', response.json()['error'])

    def test_cpf_valido_e_gravado_formatado_e_nao_repete(self):
        response = self.api.post(
            '/clients/', {'name': 'Um', 'phone': '(21) 99999-0000', 'document': '52998224725'}, format='json'
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Client.objects.get(name='Um').document, '529.982.247-25')

        duplicate = self.api.post(
            '/clients/', {'name': 'Dois', 'phone': '(21) 99999-0000', 'document': '529.982.247-25'}, format='json'
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn('CPF/CNPJ', duplicate.json()['error']['document'][0])

    def test_cpf_repetido_em_outra_imobiliaria_nao_conta(self):
        Client.objects.create(agency=self.other_agency, name='De outra', document='529.982.247-25')

        response = self.api.post(
            '/clients/', {'name': 'Um', 'phone': '(21) 99999-0000', 'document': '529.982.247-25'}, format='json'
        )

        self.assertEqual(response.status_code, 201, response.content)

    def test_cnpj_valido_e_aceito(self):
        response = self.api.post(
            '/owners/', {'name': 'Empresa', 'email': 'e@e.com', 'document': '11.222.333/0001-81'}, format='json'
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Owner.objects.get(name='Empresa').document, '11.222.333/0001-81')

    def test_cliente_e_proprietario_exigem_um_contato(self):
        client = self.api.post('/clients/', {'name': 'Só nome'}, format='json')
        owner = self.api.post('/owners/', {'name': 'Só nome'}, format='json')

        self.assertEqual(client.status_code, 400)
        self.assertEqual(owner.status_code, 400)
        self.assertIn('telefone ou e-mail', client.json()['error']['phone'][0])

    def test_cadastro_antigo_sem_contato_continua_editavel(self):
        record = Client.objects.create(agency=self.agency, name='Antigo')

        response = self.api.patch(f'/clients/{record.id}/', {'name': 'Renomeado'}, format='json')

        self.assertEqual(response.status_code, 200, response.content)

    def test_telefone_curto_e_recusado_no_cliente(self):
        response = self.api.post('/clients/', {'name': 'Ana', 'phone': '(12) 3'}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('phone', response.json()['error'])


class PlanLimitTests(QATestCase):
    def setUp(self):
        super().setUp()
        self.plan = Plan.objects.create(name='Plano 1', property_limit=2)
        self.agency.plan = self.plan
        self.agency.save()
        self.property_type = PropertyType.objects.create(name='Casa')

    def _create(self):
        return self.api.post('/properties/', {'type': str(self.property_type.id)}, format='json')

    def test_recusa_o_imovel_acima_do_limite_do_plano(self):
        self.assertEqual(self._create().status_code, 201)
        self.assertEqual(self._create().status_code, 201)

        response = self._create()

        self.assertEqual(response.status_code, 400)
        self.assertIn('Plano 1', response.json()['error'][0])
        self.assertEqual(Property.objects.filter(agency=self.agency).count(), 2)

    def test_imovel_excluido_libera_a_vaga(self):
        self._create()
        second = self._create().json()['data']['id']
        self.api.delete(f'/properties/{second}/')

        self.assertEqual(self._create().status_code, 201)

    def test_sem_limite_no_plano_nao_ha_teto(self):
        self.plan.property_limit = None
        self.plan.save()

        for _ in range(3):
            self.assertEqual(self._create().status_code, 201)

    def test_edicao_nao_e_barrada_pelo_limite(self):
        created = self._create().json()['data']['id']
        self._create()

        response = self.api.patch(f'/properties/{created}/', {'name': 'Editado'}, format='json')

        self.assertEqual(response.status_code, 200, response.content)


class DashboardTypesTests(QATestCase):
    def test_tipos_trazem_outros_para_a_fatia_fechar_no_total(self):
        names = ['Apartamento', 'Casa', 'Cobertura', 'Terreno', 'Loja']
        types = {name: PropertyType.objects.create(name=name) for name in names}
        counts = {'Apartamento': 4, 'Casa': 3, 'Cobertura': 2, 'Terreno': 1, 'Loja': 1}

        for name, total in counts.items():
            for _ in range(total):
                Property.objects.create(agency=self.agency, type=types[name])

        data = self.api.get('/dashboard/').json()['data']

        self.assertEqual(
            data['types'],
            [
                {'name': 'Apartamento', 'count': 4},
                {'name': 'Casa', 'count': 3},
                {'name': 'Cobertura', 'count': 2},
                {'name': 'Outros', 'count': 2},
            ],
        )


class AgencySettingsSecretTests(QATestCase):
    def test_chave_secreta_nao_volta_na_resposta(self):
        AgencySettings.objects.create(agency=self.agency, recaptcha_secret_key='segredo')

        data = self.api.get('/agency-settings/').json()['data']

        self.assertNotIn('recaptcha_secret_key', data)
        self.assertTrue(data['has_recaptcha_secret_key'])

    def test_chave_secreta_e_gravada_e_pode_ser_removida(self):
        response = self.api.patch('/agency-settings/', {'recaptcha_secret_key': 'nova'}, format='json')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(AgencySettings.objects.get(agency=self.agency).recaptcha_secret_key, 'nova')
        self.assertNotIn('recaptcha_secret_key', response.json()['data'])

        self.api.patch('/agency-settings/', {'recaptcha_secret_key': ''}, format='json')
        self.assertEqual(AgencySettings.objects.get(agency=self.agency).recaptcha_secret_key, '')
