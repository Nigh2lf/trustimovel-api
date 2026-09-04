"""Testes da fila de atendimento: acesso, quem é a vez, prazos e isolamento por imobiliária."""

from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Agency, AgencySettings, Lead, LeadInteraction, User, UserPermission
from core.resources import AccessLevel
from core.services import queue as queue_service

QUEUE = '/queue/'

# Quinta-feira às 10h, dentro de qualquer expediente razoável.
BASE = timezone.make_aware(datetime(2026, 9, 3, 10, 0, 0))


def at(minutes=0):
    return BASE + timedelta(minutes=minutes)


def clock(minutes=0):
    """Congela o relógio do sistema em BASE + minutos, para prazos não dependerem da hora real."""
    return patch('django.utils.timezone.now', return_value=at(minutes))


def grant(user, resource, level):
    UserPermission.objects.update_or_create(user=user, resource=resource, defaults={'level': level})


class QueueTestCase(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name='Imobiliária Um')
        self.other_agency = Agency.objects.create(name='Imobiliária Dois')

        self.manager = User.objects.create(email='gestor@um.com', agency=self.agency, type=User.Type.USER)
        grant(self.manager, 'fila', AccessLevel.FULL)

        self.b1 = self._broker('ana@um.com', 'Ana', 0)
        self.b2 = self._broker('carlos@um.com', 'Carlos', 1)
        self.b3 = self._broker('fernanda@um.com', 'Fernanda', 2)
        self.b4 = self._broker('marcos@um.com', 'Marcos', 3, presence=User.QueuePresence.PAUSED)
        self.other_broker = self._broker('outro@dois.com', 'Outro', 0, agency=self.other_agency)

        self.settings = AgencySettings.objects.create(
            agency=self.agency,
            queue_auto_assign=False,
            queue_accept_minutes=3,
            queue_first_response_minutes=5,
            queue_business_start=time(0, 0),
            queue_business_end=time(23, 59),
            queue_business_days=[0, 1, 2, 3, 4, 5, 6],
        )

        self.api = APIClient()
        self.api.force_authenticate(user=self.manager)

    def _broker(self, email, name, order, presence=User.QueuePresence.AVAILABLE, agency=None):
        user = User.objects.create(
            email=email,
            name=name,
            agency=agency or self.agency,
            type=User.Type.BROKER,
            queue_order=order,
            queue_presence=presence,
        )
        grant(user, 'fila', AccessLevel.WRITE)
        return user

    def api_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def lead(self, name='Cliente', phone='(19) 99999-0001', agency=None):
        return Lead.objects.create(agency=agency or self.agency, name=name, phone=phone, email='')

    def enqueue(self, lead, minutes=0):
        with clock(minutes):
            return queue_service.enqueue(lead)

    def tick(self, minutes):
        with clock(minutes):
            queue_service.tick(self.agency.id)

    def wheel(self):
        return [b.email for b in queue_service.brokers_for(self.agency.id)]

    def events(self, lead):
        return list(LeadInteraction.objects.filter(lead=lead).values_list('type', flat=True))


class AccessTests(QueueTestCase):
    def test_sem_autenticacao_devolve_401(self):
        self.assertEqual(APIClient().get(QUEUE).status_code, 401)

    def test_sem_permissao_devolve_403(self):
        user = User.objects.create(email='sem@um.com', agency=self.agency, type=User.Type.USER)
        self.assertEqual(self.api_for(user).get(QUEUE).status_code, 403)

    def test_leitura_le_mas_nao_configura(self):
        user = User.objects.create(email='leitor@um.com', agency=self.agency, type=User.Type.USER)
        grant(user, 'fila', AccessLevel.READ)
        api = self.api_for(user)

        self.assertEqual(api.get(QUEUE).status_code, 200)
        self.assertEqual(api.put(f'{QUEUE}settings/', {'mode': 'RANDOM'}, format='json').status_code, 403)

    def test_corretor_entra_no_painel(self):
        response = self.api_for(self.b1).get(QUEUE)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['data']['viewer']['is_manager'])

    def test_corretor_nao_configura_nem_atribui(self):
        lead = self.enqueue(self.lead())
        api = self.api_for(self.b2)

        self.assertEqual(api.put(f'{QUEUE}settings/', {'mode': 'RANDOM'}, format='json').status_code, 403)
        response = api.post(f'{QUEUE}leads/{lead.id}/assign/', {'user': str(self.b2.id)}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_admin_da_plataforma_sem_imobiliaria_devolve_403(self):
        admin = User.objects.create(email='admin@plataforma.com', type=User.Type.ADMIN)
        self.assertEqual(self.api_for(admin).get(QUEUE).status_code, 403)


class DistributionTests(QueueTestCase):
    def test_lead_e_ofertado_ao_primeiro_da_roleta_e_ele_vai_para_o_final(self):
        lead = self.enqueue(self.lead())

        self.assertEqual(lead.queue_status, Lead.QueueStatus.OFFERED)
        self.assertEqual(lead.assigned_to, self.b1)
        self.assertEqual(lead.queue_reason, 'Rodízio')
        self.assertEqual(lead.deadline_at, at(3))
        self.assertEqual(self.wheel(), ['carlos@um.com', 'fernanda@um.com', 'marcos@um.com', 'ana@um.com'])
        self.assertEqual(self.events(lead), ['ENQUEUED', 'OFFERED'])

    def test_prazo_estourado_transfere_para_o_proximo(self):
        lead = self.enqueue(self.lead())

        self.tick(2)
        lead.refresh_from_db()
        self.assertEqual(lead.assigned_to, self.b1)

        self.tick(4)
        lead.refresh_from_db()
        self.b1.refresh_from_db()

        self.assertEqual(lead.assigned_to, self.b2)
        self.assertEqual(lead.queue_status, Lead.QueueStatus.OFFERED)
        self.assertEqual(lead.deadline_at, at(7))
        self.assertEqual(self.b1.queue_skips, 1)
        self.assertIn('EXPIRED', self.events(lead))

    def test_quem_perdeu_a_vez_nao_recebe_o_mesmo_lead_de_novo(self):
        lead = self.enqueue(self.lead())

        self.tick(4)
        self.tick(8)
        lead.refresh_from_db()
        self.assertEqual(lead.assigned_to, self.b3)

        self.tick(12)
        lead.refresh_from_db()
        self.assertEqual(lead.queue_status, Lead.QueueStatus.WAITING)
        self.assertIsNone(lead.assigned_to)
        last = LeadInteraction.objects.filter(lead=lead).latest('created_at')
        self.assertEqual(last.text, 'Todos os disponíveis já passaram por este lead')

    def test_auto_pausa_depois_de_perder_ofertas_seguidas(self):
        self.settings.queue_skips_before_pause = 2
        self.settings.queue_accept_minutes = 1
        self.settings.save()
        queue_service.set_presence(self.b2, User.QueuePresence.PAUSED, 'Almoço')
        queue_service.set_presence(self.b3, User.QueuePresence.PAUSED, 'Almoço')

        self.enqueue(self.lead(phone='(19) 99999-0002'))
        self.tick(2)
        self.enqueue(self.lead(phone='(19) 99999-0003'), minutes=2)
        self.tick(4)

        self.b1.refresh_from_db()
        self.assertEqual(self.b1.queue_presence, User.QueuePresence.PAUSED)
        self.assertIn('Pausado automaticamente', self.b1.queue_pause_reason)

    def test_atribuicao_automatica_entrega_o_lead_ja_aceito(self):
        self.settings.queue_auto_assign = True
        self.settings.save()

        lead = self.enqueue(self.lead())

        self.assertEqual(lead.queue_status, Lead.QueueStatus.ACCEPTED)
        self.assertEqual(lead.accepted_at, at(0))
        self.assertEqual(lead.deadline_at, at(5))

    def test_sla_estourado_transfere_para_o_proximo_na_atribuicao_automatica(self):
        self.settings.queue_auto_assign = True
        self.settings.save()
        lead = self.enqueue(self.lead())

        self.tick(4)
        lead.refresh_from_db()
        self.assertEqual(lead.assigned_to, self.b1)

        self.tick(6)
        lead.refresh_from_db()
        self.b1.refresh_from_db()

        self.assertEqual(lead.assigned_to, self.b2)
        self.assertEqual(lead.queue_status, Lead.QueueStatus.ACCEPTED)
        self.assertEqual(lead.deadline_at, at(11))
        self.assertTrue(lead.sla_breached)
        self.assertEqual(self.b1.queue_skips, 1)
        self.assertEqual(self.events(lead).count('SLA_BREACH'), 1)

    def test_sla_estourado_depois_do_aceite_oferta_ao_proximo(self):
        lead = self.enqueue(self.lead())
        queue_service.accept(lead, now=at(1))

        self.tick(7)
        lead.refresh_from_db()

        self.assertEqual(lead.assigned_to, self.b2)
        self.assertEqual(lead.queue_status, Lead.QueueStatus.OFFERED)
        self.assertTrue(lead.sla_breached)
        self.assertEqual(self.events(lead)[-2:], ['SLA_BREACH', 'OFFERED'])

    def test_quem_estourou_o_sla_nao_recebe_o_mesmo_lead_de_volta(self):
        self.settings.queue_auto_assign = True
        self.settings.save()
        queue_service.set_presence(self.b2, User.QueuePresence.PAUSED, 'Almoço')
        queue_service.set_presence(self.b3, User.QueuePresence.PAUSED, 'Almoço')
        lead = self.enqueue(self.lead())

        self.tick(6)
        lead.refresh_from_db()

        self.assertEqual(lead.queue_status, Lead.QueueStatus.WAITING)
        self.assertIsNone(lead.assigned_to)

    def test_modo_manual_segura_o_lead_ate_o_gestor_escolher(self):
        self.settings.queue_mode = AgencySettings.QueueMode.MANUAL
        self.settings.save()

        lead = self.enqueue(self.lead())

        self.assertEqual(lead.queue_status, Lead.QueueStatus.WAITING)
        self.assertEqual(self.events(lead), ['ENQUEUED', 'HELD'])

    def test_fora_do_expediente_segura_na_espera(self):
        self.settings.queue_business_start = time(8, 0)
        self.settings.queue_business_end = time(18, 0)
        self.settings.save()

        lead = self.enqueue(self.lead(), minutes=10 * 60)

        self.assertEqual(lead.queue_status, Lead.QueueStatus.WAITING)

        self.tick(23 * 60)
        lead.refresh_from_db()
        self.assertEqual(lead.queue_status, Lead.QueueStatus.OFFERED)

    def test_regra_de_retorno_devolve_o_cliente_ao_mesmo_corretor(self):
        first = self.enqueue(self.lead(phone='(19) 98888-0000'))
        queue_service.accept(first, now=at(1))

        again = self.enqueue(self.lead(name='De novo', phone='(19) 98888-0000'), minutes=30)

        self.assertEqual(again.assigned_to, self.b1)
        self.assertEqual(again.queue_reason, 'Regra de retorno')

    def test_menor_carga_escolhe_quem_tem_menos_em_maos(self):
        self.settings.queue_mode = AgencySettings.QueueMode.LOAD
        self.settings.queue_auto_assign = True
        self.settings.save()

        self.enqueue(self.lead(phone='(19) 90000-0001'))
        self.enqueue(self.lead(phone='(19) 90000-0002'))
        third = self.enqueue(self.lead(phone='(19) 90000-0003'))

        self.assertEqual(third.assigned_to, self.b3)
        self.assertEqual(third.queue_reason, 'Menor carga')


class ActionTests(QueueTestCase):
    def test_corretor_aceita_a_propria_oferta(self):
        lead = self.enqueue(self.lead())

        with clock(1):
            response = self.api_for(self.b1).post(f'{QUEUE}leads/{lead.id}/accept/')

        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.queue_status, Lead.QueueStatus.ACCEPTED)
        self.assertEqual(lead.deadline_at, at(6))

    def test_corretor_nao_aceita_oferta_de_outro(self):
        lead = self.enqueue(self.lead())

        response = self.api_for(self.b2).post(f'{QUEUE}leads/{lead.id}/accept/')

        self.assertEqual(response.status_code, 403)

    def test_recusa_vai_para_o_proximo_e_quem_recusou_nao_e_pausado(self):
        lead = self.enqueue(self.lead())

        with clock(1):
            response = self.api_for(self.b1).post(
                f'{QUEUE}leads/{lead.id}/decline/', {'reason': 'Em visita'}, format='json'
            )

        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.b1.refresh_from_db()
        self.assertEqual(lead.assigned_to, self.b2)
        self.assertEqual(self.b1.queue_skips, 0)

    def test_recusa_mantendo_a_posicao_volta_ao_comeco_da_fila(self):
        self.settings.queue_decline_behavior = AgencySettings.QueueDeclineBehavior.KEEP
        self.settings.save()
        lead = self.enqueue(self.lead())

        queue_service.decline(lead, 'Região que não atendo', now=at(1))

        self.assertEqual(self.wheel()[0], 'ana@um.com')

    def test_primeira_acao_registrada_marca_o_primeiro_contato(self):
        lead = self.enqueue(self.lead())
        queue_service.accept(lead, now=at(1))

        with clock(2):
            response = self.api_for(self.b1).post(
                f'{QUEUE}leads/{lead.id}/notes/', {'text': 'Liguei, agendei visita'}, format='json'
            )

        self.assertEqual(response.status_code, 201)
        lead.refresh_from_db()
        self.assertEqual(lead.queue_status, Lead.QueueStatus.IN_SERVICE)
        self.assertEqual(lead.contacted_at, at(2))
        self.assertFalse(lead.sla_breached)
        self.assertEqual(lead.status, Lead.Status.IN_CONTACT)
        self.assertEqual(self.events(lead)[-1], 'FIRST_CONTACT')

    def test_primeiro_contato_atrasado_fica_marcado(self):
        lead = self.enqueue(self.lead())
        queue_service.accept(lead, now=at(1))

        queue_service.add_note(lead, self.b1, 'Demorei', now=at(20))

        lead.refresh_from_db()
        self.assertTrue(lead.sla_breached)

    def test_interacao_pela_tela_de_leads_tambem_conta_como_primeiro_contato(self):
        grant(self.manager, 'leads', AccessLevel.WRITE)
        lead = self.enqueue(self.lead())
        queue_service.accept(lead, now=at(1))

        with clock(2):
            response = self.api.post(f'/leads/{lead.id}/interactions/', {'text': 'Falei com ele'}, format='json')

        self.assertEqual(response.status_code, 201)
        lead.refresh_from_db()
        self.assertEqual(lead.queue_status, Lead.QueueStatus.IN_SERVICE)

    def test_encerrar_qualificado_e_perdido(self):
        won = self.enqueue(self.lead(phone='(19) 97777-0001'))
        lost = self.enqueue(self.lead(phone='(19) 97777-0002'))

        with clock(1):
            self.api.post(f'{QUEUE}leads/{won.id}/close/', {'outcome': 'WON'}, format='json')
            self.api.post(
                f'{QUEUE}leads/{lost.id}/close/', {'outcome': 'LOST', 'detail': 'Sem retorno'}, format='json'
            )

        won.refresh_from_db()
        lost.refresh_from_db()
        self.assertEqual((won.queue_status, won.status), (Lead.QueueStatus.CLOSED, Lead.Status.QUALIFIED))
        self.assertEqual((lost.queue_status, lost.status), (Lead.QueueStatus.CLOSED, Lead.Status.UNQUALIFIED))

    def test_gestor_atribui_e_devolve_para_a_fila(self):
        lead = self.enqueue(self.lead())

        with clock(1):
            response = self.api.post(f'{QUEUE}leads/{lead.id}/assign/', {'user': str(self.b3.id)}, format='json')
        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.assigned_to, self.b3)
        self.assertEqual(lead.queue_reason, 'Escolha do gestor')

        with clock(2):
            response = self.api.post(f'{QUEUE}leads/{lead.id}/return/', {'reason': 'Sumiu'}, format='json')
        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertNotEqual(lead.assigned_to, self.b3)
        self.assertIn('RETURNED', self.events(lead))

    def test_lead_ja_na_fila_nao_entra_de_novo(self):
        lead = self.enqueue(self.lead())

        with clock(1):
            response = self.api.post(f'{QUEUE}leads/', {'lead': str(lead.id)}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['message'], 'Este lead já está na fila.')

    def test_presenca_e_ordem_da_roleta(self):
        api = self.api_for(self.b1)
        response = api.post(
            f'{QUEUE}brokers/{self.b1.id}/presence/', {'presence': 'PAUSED', 'pause_reason': 'Almoço'}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.b1.refresh_from_db()
        self.assertEqual(self.b1.queue_pause_reason, 'Almoço')

        response = api.post(f'{QUEUE}brokers/{self.b2.id}/presence/', {'presence': 'PAUSED'}, format='json')
        self.assertEqual(response.status_code, 403)

        self.api.post(f'{QUEUE}brokers/{self.b3.id}/move/', {'direction': -1}, format='json')
        self.assertEqual(self.wheel()[1], 'fernanda@um.com')

        self.api.post(f'{QUEUE}brokers/{self.b3.id}/toggle/')
        self.b3.refresh_from_db()
        self.assertFalse(self.b3.in_queue)

    def test_configuracao_salva_sem_prefixo(self):
        response = self.api.put(
            f'{QUEUE}settings/',
            {
                'mode': 'RANDOM',
                'auto_assign': True,
                'decline_behavior': 'KEEP',
                'accept_minutes': 2,
                'first_response_minutes': 10,
                'max_active_per_broker': 0,
                'return_window_days': 15,
                'skips_before_pause': 3,
                'business_start': '09:00',
                'business_end': '19:00',
                'business_days': [5, 1, 2, 3, 4],
                'off_hours': 'DISTRIBUTE',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.queue_mode, 'RANDOM')
        self.assertEqual(self.settings.queue_business_days, [1, 2, 3, 4, 5])
        self.assertEqual(response.json()['data']['business_start'], '09:00')

    def test_configuracao_invalida_devolve_o_campo(self):
        response = self.api.patch(f'{QUEUE}settings/', {'accept_minutes': 0}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0]['field'], 'accept_minutes')

    def test_comando_queuetick_expira_ofertas(self):
        lead = self.enqueue(self.lead())

        with clock(4):
            call_command('queuetick')

        lead.refresh_from_db()
        self.assertEqual(lead.assigned_to, self.b2)


class VisibilityTests(QueueTestCase):
    def test_gestor_ve_a_fila_inteira_e_corretor_so_o_que_esta_com_ele(self):
        first = self.enqueue(self.lead(phone='(19) 96666-0001'))
        self.enqueue(self.lead(phone='(19) 96666-0002'))

        with clock(1):
            manager_leads = self.api.get(QUEUE).json()['data']['leads']
            broker_leads = self.api_for(self.b1).get(QUEUE).json()['data']['leads']

        self.assertEqual(len(manager_leads), 2)
        self.assertEqual([lead['id'] for lead in broker_leads], [str(first.id)])

    def test_outra_imobiliaria_nao_enxerga_nem_age(self):
        lead = self.enqueue(self.lead())
        other_manager = User.objects.create(email='gestor@dois.com', agency=self.other_agency, type=User.Type.USER)
        grant(other_manager, 'fila', AccessLevel.FULL)
        api = self.api_for(other_manager)

        with clock(1):
            self.assertEqual(api.get(QUEUE).json()['data']['leads'], [])
            self.assertEqual(api.post(f'{QUEUE}leads/{lead.id}/accept/').status_code, 404)
            self.assertEqual(api.post(f'{QUEUE}leads/', {'lead': str(lead.id)}, format='json').status_code, 404)
            response = api.post(f'{QUEUE}leads/{lead.id}/assign/', {'user': str(self.b1.id)}, format='json')
            self.assertEqual(response.status_code, 404)

    def test_estado_traz_tentativas_e_eventos(self):
        lead = self.enqueue(self.lead())
        queue_service.decline(lead, 'Não é minha região', now=at(1))

        with clock(2):
            data = self.api.get(QUEUE).json()['data']
        item = next(entry for entry in data['leads'] if entry['id'] == str(lead.id))

        self.assertEqual(item['attempts'], [str(self.b1.id)])
        self.assertEqual([event['type'] for event in item['events']][:3], ['ENQUEUED', 'OFFERED', 'DECLINED'])
        self.assertEqual(len(data['brokers']), 4)


class UserTypeTests(QueueTestCase):
    def setUp(self):
        super().setUp()
        grant(self.manager, 'usuarios', AccessLevel.FULL)

    def test_gestor_cadastra_corretor(self):
        response = self.api.post(
            '/users/',
            {'email': 'novo@um.com', 'name': 'Novo', 'password': 'Senha!123', 'type': 'BROKER', 'team': 'Vendas'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email='novo@um.com')
        self.assertEqual(user.type, User.Type.BROKER)
        self.assertEqual(user.team, 'Vendas')
        self.assertTrue(user.in_queue)

    def test_gestor_nao_cria_admin_da_plataforma(self):
        response = self.api.post(
            '/users/',
            {'email': 'novo@um.com', 'password': 'Senha!123', 'type': 'ADMIN'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_lista_de_corretores_para_o_lead(self):
        grant(self.manager, 'leads', AccessLevel.READ)

        response = self.api.get('/leads/brokers/', {'search': 'carlos'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['name'] for item in response.json()['data']['results']], ['Carlos'])

    def test_lead_nao_aceita_corretor_de_outra_imobiliaria(self):
        grant(self.manager, 'leads', AccessLevel.WRITE)

        response = self.api.post(
            '/leads/',
            {
                'name': 'Cliente',
                'email': 'c@c.com',
                'phone': '(19) 90000-0000',
                'source': 'SITE',
                'interest': 'PURCHASE',
                'assigned_to': str(self.other_broker.id),
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
