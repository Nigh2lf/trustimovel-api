"""Testes do assistente Theo.

Cobrem o que não pode quebrar calado: a exigência de autenticação, o isolamento das
conversas por usuário, o escopo por imobiliária nas ferramentas de consulta e o respeito
ao permissionamento por recurso. O Grok é sempre simulado — nenhum teste sai da máquina.
"""

import json
from datetime import timedelta
from unittest import mock
from urllib.error import URLError

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    Agency,
    AssistantConversation,
    AssistantMessage,
    Broker,
    City,
    Client,
    Country,
    Feature,
    Lead,
    Neighborhood,
    Property,
    PropertyPrice,
    PropertyType,
    State,
    Task,
    User,
    UserPermission,
)
from core.resources import AccessLevel
from core.services import assistant


def grant(user, resource, level):
    UserPermission.objects.update_or_create(
        user=user, resource=resource, defaults={'level': level}
    )
    # O mapa de permissões é cacheado por instância; invalida para o teste enxergar a concessão.
    if hasattr(user, '_permission_map'):
        del user._permission_map


def grok_http_response(message):
    """Simula o retorno do urlopen com uma resposta do Grok no formato da API."""
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {'choices': [{'message': message}]}
    ).encode('utf-8')

    return response


class AssistantTestCase(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name='Imobiliária Um')
        self.other_agency = Agency.objects.create(name='Imobiliária Dois')

        self.user = User.objects.create(
            email='corretor@um.com', agency=self.agency, type=User.Type.USER
        )
        self.other_user = User.objects.create(
            email='corretor@dois.com', agency=self.other_agency, type=User.Type.USER
        )

        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.user)


class AssistantAuthTests(AssistantTestCase):
    def test_chat_sem_token_retorna_401(self):
        response = APIClient().post('/assistant/chat/', {'message': 'Oi'}, format='json')

        self.assertEqual(response.status_code, 401)

    def test_conversas_sem_token_retorna_401(self):
        response = APIClient().get('/assistant/conversations/')

        self.assertEqual(response.status_code, 401)

    def test_chat_exige_vinculo_com_imobiliaria(self):
        admin = User.objects.create(email='admin@plataforma.com', type=User.Type.ADMIN)
        client_api = APIClient()
        client_api.force_authenticate(user=admin)

        response = client_api.post('/assistant/chat/', {'message': 'Oi'}, format='json')

        self.assertEqual(response.status_code, 400)


class AssistantChatTests(AssistantTestCase):
    @mock.patch('core.services.assistant.urlopen')
    def test_chat_responde_e_grava_historico(self, mocked_urlopen):
        mocked_urlopen.return_value = grok_http_response({'content': 'Você tem 2 imóveis.'})

        response = self.client_api.post(
            '/assistant/chat/', {'message': 'Quantos imóveis tenho?'}, format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['reply'], 'Você tem 2 imóveis.')

        conversation = AssistantConversation.objects.get(user=self.user)
        self.assertEqual(conversation.title, 'Quantos imóveis tenho?')
        self.assertEqual(conversation.messages.count(), 2)

        mocked_urlopen.return_value = grok_http_response({'content': 'Nenhum lead novo.'})
        response = self.client_api.post(
            '/assistant/chat/',
            {'message': 'E leads novos?', 'conversation': str(conversation.id)},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(conversation.messages.count(), 4)
        self.assertEqual(AssistantConversation.objects.filter(user=self.user).count(), 1)

    @mock.patch('core.services.assistant.urlopen')
    def test_chat_executa_ferramenta_com_dados_da_imobiliaria(self, mocked_urlopen):
        grant(self.user, 'leads', AccessLevel.READ)
        Lead.objects.create(agency=self.agency, name='Lead da casa')
        Lead.objects.create(agency=self.other_agency, name='Lead alheio')

        tool_call_message = {
            'content': None,
            'tool_calls': [
                {
                    'id': 'call_1',
                    'function': {
                        'name': 'query_records',
                        'arguments': '{"entity": "leads", "operation": "count"}',
                    },
                }
            ],
        }
        mocked_urlopen.side_effect = [
            grok_http_response(tool_call_message),
            grok_http_response({'content': 'Você tem 1 lead.'}),
        ]

        response = self.client_api.post(
            '/assistant/chat/', {'message': 'Quantos leads tenho?'}, format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['reply'], 'Você tem 1 lead.')

        # A segunda chamada ao Grok precisa levar o resultado da ferramenta, contando só a agência do usuário.
        second_request = mocked_urlopen.call_args_list[1].args[0]
        payload = json.loads(second_request.data.decode('utf-8'))
        tool_message = payload['messages'][-1]
        self.assertEqual(tool_message['role'], 'tool')
        self.assertEqual(json.loads(tool_message['content'])['count'], 1)

    @mock.patch('core.services.assistant.urlopen')
    def test_rodadas_esgotadas_forcam_resposta_final(self, mocked_urlopen):
        grant(self.user, 'leads', AccessLevel.READ)

        tool_call_message = {
            'content': None,
            'tool_calls': [
                {
                    'id': 'call_1',
                    'function': {
                        'name': 'query_records',
                        'arguments': '{"entity": "leads", "operation": "count"}',
                    },
                }
            ],
        }
        mocked_urlopen.side_effect = [
            grok_http_response(tool_call_message) for _round in range(assistant.MAX_TOOL_ROUNDS)
        ] + [grok_http_response({'content': 'Resumo com o que consegui consultar.'})]

        response = self.client_api.post(
            '/assistant/chat/', {'message': 'Um resumo de tudo?'}, format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['reply'], 'Resumo com o que consegui consultar.')

        # A chamada final precisa desligar as ferramentas para o Grok ser obrigado a responder.
        final_request = mocked_urlopen.call_args_list[-1].args[0]
        payload = json.loads(final_request.data.decode('utf-8'))
        self.assertEqual(payload['tool_choice'], 'none')

    @mock.patch('core.services.assistant.urlopen')
    def test_grok_indisponivel_retorna_503_sem_gravar(self, mocked_urlopen):
        mocked_urlopen.side_effect = URLError('down')

        response = self.client_api.post(
            '/assistant/chat/', {'message': 'Quantos imóveis?'}, format='json'
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(AssistantConversation.objects.count(), 0)
        self.assertEqual(AssistantMessage.objects.count(), 0)

    def test_chat_nao_aceita_conversa_de_outro_usuario(self):
        conversation = AssistantConversation.objects.create(
            agency=self.other_agency, user=self.other_user, title='Alheia'
        )

        response = self.client_api.post(
            '/assistant/chat/',
            {'message': 'Oi', 'conversation': str(conversation.id)},
            format='json',
        )

        self.assertEqual(response.status_code, 404)


class AssistantConversationTests(AssistantTestCase):
    def test_lista_so_as_proprias_conversas(self):
        mine = AssistantConversation.objects.create(
            agency=self.agency, user=self.user, title='Minha'
        )
        AssistantConversation.objects.create(
            agency=self.other_agency, user=self.other_user, title='Alheia'
        )

        response = self.client_api.get('/assistant/conversations/')

        self.assertEqual(response.status_code, 200)
        results = response.data['data']['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], str(mine.id))

    def test_conversa_de_outro_usuario_retorna_404(self):
        conversation = AssistantConversation.objects.create(
            agency=self.other_agency, user=self.other_user, title='Alheia'
        )

        response = self.client_api.get(f'/assistant/conversations/{conversation.id}/')

        self.assertEqual(response.status_code, 404)

    def test_excluir_conversa_e_soft_delete(self):
        conversation = AssistantConversation.objects.create(
            agency=self.agency, user=self.user, title='Minha'
        )

        response = self.client_api.delete(f'/assistant/conversations/{conversation.id}/')

        self.assertEqual(response.status_code, 204)
        conversation.refresh_from_db()
        self.assertIsNotNone(conversation.deleted_at)


class AssistantPropertySearchTests(AssistantTestCase):
    def setUp(self):
        super().setUp()
        country = Country.objects.create(name='Brasil', code='BRA')
        self.state = State.objects.create(country=country, name='Rio de Janeiro', abbreviation='RJ')
        self.city = City.objects.create(state=self.state, name='Teresópolis', ibge_code='3305802')
        self.neighborhood = Neighborhood.objects.create(city=self.city, name='Tijuca')
        self.apartment = PropertyType.objects.create(name='Apartamento')
        Property.objects.create(
            agency=self.agency, code='900', type=self.apartment, neighborhood=self.neighborhood
        )

    def test_resolve_traduz_nomes_em_ids(self):
        result = assistant._resolve_property_search(
            self.user,
            {
                'purpose': 'SALE',
                'property_type': 'apartamento',
                'neighborhood': 'tijuca',
                'max_price': 500000,
                'min_bedrooms': 3,
                'in_condominium': False,
            },
            'apartamento de 3 quartos na tijuca até 500 mil fora de condomínio',
        )

        self.assertEqual(result['params']['purpose'], 'SALE')
        self.assertEqual(result['params']['type'], str(self.apartment.id))
        self.assertEqual(result['params']['neighborhood'], str(self.neighborhood.id))
        self.assertEqual(result['params']['price_max'], 500000.0)
        self.assertEqual(result['params']['bedrooms_min'], 3)
        self.assertFalse(result['params']['has_condominium'])
        self.assertEqual(result['unmatched'], [])

    def test_resolve_prefere_nome_exato_ao_parcial(self):
        # "Barra da Tijuca" vem antes na ordem alfabética; só o nome exato segura o match certo.
        Neighborhood.objects.create(city=self.city, name='Barra da Tijuca')

        result = assistant._resolve_property_search(
            self.user, {'neighborhood': 'tijuca'}, 'imóveis na tijuca'
        )

        self.assertEqual(result['params']['neighborhood'], str(self.neighborhood.id))

    def test_resolve_marca_o_que_nao_encontrou(self):
        result = assistant._resolve_property_search(
            self.user,
            {'property_type': 'castelo', 'neighborhood': 'atlantida'},
            'castelo em atlantida',
        )

        self.assertNotIn('type', result['params'])
        self.assertNotIn('neighborhood', result['params'])
        self.assertEqual(len(result['unmatched']), 2)

    def test_resolve_recupera_preco_que_o_modelo_perdeu(self):
        result = assistant._resolve_property_search(
            self.user, {'property_type': 'apartamento'}, 'apartamento na tijuca ate 4 milhoes'
        )

        self.assertEqual(result['params']['price_max'], 4000000.0)
        self.assertNotIn('price_min', result['params'])

        result = assistant._resolve_property_search(
            self.user, {}, 'imoveis entre 500 mil e 1,2 milhoes'
        )

        self.assertEqual(result['params']['price_min'], 500000.0)
        self.assertEqual(result['params']['price_max'], 1200000.0)

    def test_resolve_descarta_busca_com_numeros(self):
        result = assistant._resolve_property_search(
            self.user,
            {'search': '4 quartos? min_price? max_price 4000000'},
            'apartamento de 4 quartos ate 4 milhoes',
        )

        self.assertNotIn('search', result['params'])

    def test_resolve_descarta_o_que_o_pedido_nao_citou(self):
        result = assistant._resolve_property_search(
            self.user,
            {
                'neighborhood': 'tijuca',
                'city': 'Rio de Janeiro',
                'state': 'RJ',
                'in_condominium': True,
                'featured': True,
                'search': 'apartamento na tijuca',
            },
            'apartamento na tijuca',
        )

        self.assertIn('neighborhood', result['params'])
        self.assertNotIn('city', result['params'])
        self.assertNotIn('state', result['params'])
        self.assertNotIn('has_condominium', result['params'])
        self.assertNotIn('featured', result['params'])
        self.assertNotIn('search', result['params'])
        self.assertEqual(result['unmatched'], [])

    @mock.patch('core.services.assistant.urlopen')
    def test_endpoint_interpreta_e_devolve_parametros(self, mocked_urlopen):
        grant(self.user, 'imoveis', AccessLevel.READ)
        mocked_urlopen.return_value = grok_http_response(
            {
                'content': None,
                'tool_calls': [
                    {
                        'id': 'call_1',
                        'function': {
                            'name': 'set_property_search',
                            'arguments': json.dumps(
                                {'purpose': 'SALE', 'property_type': 'Apartamento', 'min_bedrooms': 3}
                            ),
                        },
                    }
                ],
            }
        )

        response = self.client_api.post(
            '/assistant/property-search/',
            {'query': 'Apartamento de 3 quartos à venda'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertEqual(data['params']['type'], str(self.apartment.id))
        self.assertEqual(data['params']['bedrooms_min'], 3)

    def test_endpoint_exige_permissao_de_imoveis(self):
        response = self.client_api.post(
            '/assistant/property-search/', {'query': 'Casa com piscina'}, format='json'
        )

        self.assertEqual(response.status_code, 403)

    def test_endpoint_sem_token_retorna_401(self):
        response = APIClient().post(
            '/assistant/property-search/', {'query': 'Casa'}, format='json'
        )

        self.assertEqual(response.status_code, 401)


class AssistantToolTests(AssistantTestCase):
    def test_query_records_isola_por_imobiliaria_e_ignora_excluidos(self):
        grant(self.user, 'leads', AccessLevel.READ)
        Lead.objects.create(agency=self.agency, name='Ativo')
        Lead.objects.create(agency=self.other_agency, name='Alheio')
        deleted = Lead.objects.create(agency=self.agency, name='Excluído')
        deleted.delete()

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user, {'entity': 'leads', 'operation': 'count'}
        )

        self.assertEqual(result['count'], 1)

    def test_query_records_sem_permissao_retorna_erro(self):
        Lead.objects.create(agency=self.agency, name='Ativo')

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user, {'entity': 'leads', 'operation': 'count'}
        )

        self.assertIn('error', result)

    def test_query_records_filtra_por_periodo(self):
        grant(self.user, 'leads', AccessLevel.READ)
        Lead.objects.create(agency=self.agency, name='Deste mês')
        old = Lead.objects.create(agency=self.agency, name='Antigo')
        Lead.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=60)
        )

        start = timezone.localdate().replace(day=1)
        result = assistant.TOOL_HANDLERS['query_records'](
            self.user,
            {'entity': 'leads', 'operation': 'count', 'created_from': start.isoformat()},
        )

        self.assertEqual(result['count'], 1)

    def test_query_records_agrupa_por_status(self):
        grant(self.user, 'leads', AccessLevel.READ)
        Lead.objects.create(agency=self.agency, name='Novo')
        Lead.objects.create(
            agency=self.agency, name='Convertido', status=Lead.Status.CONVERTED
        )

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user, {'entity': 'leads', 'operation': 'count', 'group_by': 'status'}
        )

        groups = {group['value']: group['count'] for group in result['groups']}
        self.assertEqual(groups[Lead.Status.NEW], 1)
        self.assertEqual(groups[Lead.Status.CONVERTED], 1)

    def test_query_records_tarefas_atrasadas(self):
        grant(self.user, 'tarefas', AccessLevel.READ)
        yesterday = timezone.localdate() - timedelta(days=1)
        Task.objects.create(agency=self.agency, title='Atrasada', due_date=yesterday)
        Task.objects.create(
            agency=self.agency,
            title='Concluída',
            due_date=yesterday,
            status=Task.Status.DONE,
        )
        Task.objects.create(
            agency=self.agency,
            title='Futura',
            due_date=timezone.localdate() + timedelta(days=1),
        )

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user, {'entity': 'tasks', 'operation': 'count', 'overdue': True}
        )

        self.assertEqual(result['count'], 1)

    def test_query_records_lista_registros(self):
        grant(self.user, 'imoveis', AccessLevel.READ)
        Property.objects.create(agency=self.agency, code='100')

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user, {'entity': 'properties', 'operation': 'list'}
        )

        self.assertEqual(result['count'], 1)
        self.assertEqual(result['results'][0]['code'], '100')

    def test_query_records_imovel_mais_caro_por_tipo(self):
        grant(self.user, 'imoveis', AccessLevel.READ)
        apartment = PropertyType.objects.create(name='Apartamento')
        house = PropertyType.objects.create(name='Casa')
        cheap = Property.objects.create(agency=self.agency, code='300', type=apartment)
        expensive = Property.objects.create(agency=self.agency, code='301', type=apartment)
        mansion = Property.objects.create(agency=self.agency, code='302', type=house)
        PropertyPrice.objects.create(property=cheap, purpose=PropertyPrice.Purpose.SALE, amount=500000)
        PropertyPrice.objects.create(property=expensive, purpose=PropertyPrice.Purpose.SALE, amount=900000)
        PropertyPrice.objects.create(property=mansion, purpose=PropertyPrice.Purpose.SALE, amount=2000000)

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user,
            {
                'entity': 'properties',
                'operation': 'list',
                'property_type': 'apartamento',
                'order_by': 'price_desc',
                'limit': 1,
            },
        )

        self.assertEqual(result['count'], 2)
        self.assertEqual(result['results'][0]['code'], '301')
        self.assertEqual(float(result['results'][0]['sale_price']), 900000.0)

    def test_query_records_agregados_de_preco(self):
        grant(self.user, 'imoveis', AccessLevel.READ)
        with_low_price = Property.objects.create(agency=self.agency, code='400')
        with_high_price = Property.objects.create(agency=self.agency, code='401')
        Property.objects.create(agency=self.agency, code='402')
        PropertyPrice.objects.create(
            property=with_low_price, purpose=PropertyPrice.Purpose.SALE, amount=100000
        )
        PropertyPrice.objects.create(
            property=with_high_price, purpose=PropertyPrice.Purpose.SALE, amount=300000
        )

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user, {'entity': 'properties', 'operation': 'count', 'purpose': 'SALE'}
        )

        self.assertEqual(result['count'], 3)
        self.assertEqual(result['price_stats']['with_price'], 2)
        self.assertEqual(result['price_stats']['min'], 100000.0)
        self.assertEqual(result['price_stats']['max'], 300000.0)
        self.assertEqual(result['price_stats']['avg'], 200000.0)

    def test_query_records_status_invalido_retorna_erro(self):
        grant(self.user, 'leads', AccessLevel.READ)

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user, {'entity': 'leads', 'operation': 'count', 'status': 'INEXISTENTE'}
        )

        self.assertIn('error', result)

    def test_query_records_busca_textual(self):
        grant(self.user, 'leads', AccessLevel.READ)
        Lead.objects.create(agency=self.agency, name='Carlos Silva')
        Lead.objects.create(agency=self.agency, name='Maria Souza')

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user, {'entity': 'leads', 'operation': 'count', 'search': 'carlos'}
        )

        self.assertEqual(result['count'], 1)

    def test_query_records_filtra_e_agrupa_por_responsavel(self):
        grant(self.user, 'leads', AccessLevel.READ)
        joao = Broker.objects.create(agency=self.agency, name='João Souza')
        ana = Broker.objects.create(agency=self.agency, name='Ana Lima')
        Lead.objects.create(agency=self.agency, name='Lead 1', responsible=joao)
        Lead.objects.create(agency=self.agency, name='Lead 2', responsible=joao)
        Lead.objects.create(agency=self.agency, name='Lead 3', responsible=ana)

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user, {'entity': 'leads', 'operation': 'count', 'responsible': 'Souza'}
        )
        self.assertEqual(result['count'], 2)

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user, {'entity': 'leads', 'operation': 'count', 'group_by': 'responsible'}
        )
        groups = {group['value']: group['count'] for group in result['groups']}
        self.assertEqual(groups['João Souza'], 2)
        self.assertEqual(groups['Ana Lima'], 1)

    def test_query_records_faixa_de_preco(self):
        grant(self.user, 'imoveis', AccessLevel.READ)

        for code, amount in (('500', 100000), ('501', 500000), ('502', 900000)):
            instance = Property.objects.create(agency=self.agency, code=code)
            PropertyPrice.objects.create(
                property=instance, purpose=PropertyPrice.Purpose.SALE, amount=amount
            )

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user,
            {
                'entity': 'properties',
                'operation': 'list',
                'min_price': 200000,
                'max_price': 600000,
            },
        )

        self.assertEqual(result['count'], 1)
        self.assertEqual(result['results'][0]['code'], '501')

    def test_query_records_leads_sem_contato(self):
        grant(self.user, 'leads', AccessLevel.READ)
        today = timezone.localdate()
        Lead.objects.create(
            agency=self.agency, name='Contato antigo', last_contact_at=today - timedelta(days=10)
        )
        Lead.objects.create(agency=self.agency, name='Contato recente', last_contact_at=today)
        never_contacted = Lead.objects.create(agency=self.agency, name='Nunca contatado antigo')
        Lead.objects.filter(pk=never_contacted.pk).update(
            created_at=timezone.now() - timedelta(days=20)
        )
        Lead.objects.create(agency=self.agency, name='Nunca contatado novo')

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user, {'entity': 'leads', 'operation': 'count', 'no_contact_days': 7}
        )

        self.assertEqual(result['count'], 2)

    def test_query_records_tarefas_por_prazo(self):
        grant(self.user, 'tarefas', AccessLevel.READ)
        today = timezone.localdate()
        Task.objects.create(agency=self.agency, title='Desta semana', due_date=today)
        Task.objects.create(
            agency=self.agency, title='Mês que vem', due_date=today + timedelta(days=30)
        )

        result = assistant.TOOL_HANDLERS['query_records'](
            self.user,
            {
                'entity': 'tasks',
                'operation': 'count',
                'due_from': today.isoformat(),
                'due_to': (today + timedelta(days=2)).isoformat(),
            },
        )

        self.assertEqual(result['count'], 1)

    def test_get_record_detalhe_do_imovel(self):
        grant(self.user, 'imoveis', AccessLevel.READ)
        apartment = PropertyType.objects.create(name='Apartamento')
        pool = Feature.objects.create(name='Piscina')
        instance = Property.objects.create(
            agency=self.agency, code='600', type=apartment, bedrooms=3
        )
        instance.features.add(pool)
        PropertyPrice.objects.create(
            property=instance, purpose=PropertyPrice.Purpose.SALE, amount=750000
        )

        result = assistant.TOOL_HANDLERS['get_record'](
            self.user, {'entity': 'properties', 'query': '600'}
        )

        self.assertEqual(result['code'], '600')
        self.assertEqual(result['type'], 'Apartamento')
        self.assertEqual(result['bedrooms'], 3)
        self.assertEqual(result['prices'][0]['amount'], 750000.0)
        self.assertIn('Piscina', result['features'])

    def test_get_record_ambiguidade_e_nao_encontrado(self):
        grant(self.user, 'clientes', AccessLevel.READ)
        Client.objects.create(agency=self.agency, name='Maria Silva')
        Client.objects.create(agency=self.agency, name='Maria Souza')

        result = assistant.TOOL_HANDLERS['get_record'](
            self.user, {'entity': 'clients', 'query': 'Maria'}
        )
        self.assertIn('error', result)
        self.assertEqual(len(result['candidates']), 2)

        result = assistant.TOOL_HANDLERS['get_record'](
            self.user, {'entity': 'clients', 'query': 'Inexistente'}
        )
        self.assertIn('error', result)
        self.assertNotIn('candidates', result)

    def test_get_record_sem_permissao(self):
        Property.objects.create(agency=self.agency, code='700')

        result = assistant.TOOL_HANDLERS['get_record'](
            self.user, {'entity': 'properties', 'query': '700'}
        )

        self.assertIn('error', result)

    def test_get_record_nao_vaza_outra_imobiliaria(self):
        grant(self.user, 'imoveis', AccessLevel.READ)
        Property.objects.create(agency=self.other_agency, code='800')

        result = assistant.TOOL_HANDLERS['get_record'](
            self.user, {'entity': 'properties', 'query': '800'}
        )

        self.assertIn('error', result)

    def test_dashboard_summary_respeita_permissao(self):
        result = assistant.TOOL_HANDLERS['dashboard_summary'](self.user, {})
        self.assertIn('error', result)

        grant(self.user, 'dashboard', AccessLevel.READ)
        Property.objects.create(agency=self.agency, code='200')

        result = assistant.TOOL_HANDLERS['dashboard_summary'](self.user, {})
        self.assertEqual(result['properties']['total'], 1)

    def test_sales_report_respeita_permissao(self):
        result = assistant.TOOL_HANDLERS['sales_report'](self.user, {})

        self.assertIn('error', result)
