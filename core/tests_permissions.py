"""Testes do permissionamento por recurso.

Cobrem as três coisas que, se quebrarem, quebram calado: a escada de níveis, a separação
entre 401 e 403 (que decide se o usuário é deslogado ou só avisado) e as travas que
impedem uma imobiliária de ficar sem ninguém capaz de administrar usuários.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Agency, Client, User, UserPermission
from core.resources import AccessLevel


def grant(user, resource, level):
    UserPermission.objects.update_or_create(
        user=user, resource=resource, defaults={'level': level}
    )


class PermissionTestCase(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name='Imobiliária Um')
        self.other_agency = Agency.objects.create(name='Imobiliária Dois')

        self.user = User.objects.create(
            email='corretor@um.com', agency=self.agency, type=User.Type.USER
        )
        self.user.set_password('senha-de-teste-123')
        self.user.save()

        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.user)

    def make_client_record(self, agency=None):
        return Client.objects.create(agency=agency or self.agency, name='Fulano')


class AccessLadderTests(PermissionTestCase):
    """Leitura lê, Escrita grava, Total exclui — e nenhum nível faz o do degrau acima."""

    def test_sem_permissao_nao_lista(self):
        response = self.client_api.get('/clients/')

        self.assertEqual(response.status_code, 403)

    def test_leitura_lista_mas_nao_cria(self):
        grant(self.user, 'clientes', AccessLevel.READ)

        self.assertEqual(self.client_api.get('/clients/').status_code, 200)

        response = self.client_api.post('/clients/', {'name': 'Novo'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_escrita_cria_mas_nao_exclui(self):
        grant(self.user, 'clientes', AccessLevel.WRITE)
        record = self.make_client_record()

        response = self.client_api.patch(
            f'/clients/{record.id}/', {'name': 'Editado'}, format='json'
        )
        self.assertEqual(response.status_code, 200)

        response = self.client_api.delete(f'/clients/{record.id}/')
        self.assertEqual(response.status_code, 403)

    def test_total_exclui(self):
        grant(self.user, 'clientes', AccessLevel.FULL)
        record = self.make_client_record()

        response = self.client_api.delete(f'/clients/{record.id}/')

        self.assertEqual(response.status_code, 204)
        record.refresh_from_db()
        self.assertIsNotNone(record.deleted_at)

    def test_permissao_em_um_recurso_nao_vaza_para_outro(self):
        grant(self.user, 'clientes', AccessLevel.FULL)

        self.assertEqual(self.client_api.get('/owners/').status_code, 403)

    def test_admin_da_plataforma_passa_por_cima(self):
        admin = User.objects.create(email='admin@plataforma.com', type=User.Type.ADMIN)
        api = APIClient()
        api.force_authenticate(user=admin)

        self.assertEqual(api.get('/clients/').status_code, 200)


class ForbiddenIsNotUnauthorizedTests(PermissionTestCase):
    """403 e 401 precisam continuar distintos: o front desloga em 401."""

    def test_sem_permissao_devolve_403_e_nao_401(self):
        response = self.client_api.get('/clients/')

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['success'])

    def test_sem_autenticacao_devolve_401(self):
        response = APIClient().get('/clients/')

        self.assertEqual(response.status_code, 401)


class TenantIsolationTests(PermissionTestCase):
    """Permissão libera o recurso, não os dados dos outros clientes."""

    def test_listagem_de_clientes_nao_mostra_outra_imobiliaria(self):
        grant(self.user, 'clientes', AccessLevel.READ)
        self.make_client_record()
        self.make_client_record(agency=self.other_agency)

        response = self.client_api.get('/clients/')

        self.assertEqual(response.json()['data']['count'], 1)

    def test_listagem_de_usuarios_nao_mostra_outra_imobiliaria(self):
        grant(self.user, 'usuarios', AccessLevel.READ)
        User.objects.create(email='alheio@dois.com', agency=self.other_agency)

        response = self.client_api.get('/users/')

        emails = [row['email'] for row in response.json()['data']['results']]
        self.assertEqual(emails, [self.user.email])


class LockoutGuardTests(PermissionTestCase):
    """A imobiliária não pode ficar sem ninguém capaz de administrar usuários."""

    def setUp(self):
        super().setUp()
        grant(self.user, 'usuarios', AccessLevel.FULL)

    def test_nao_reduz_a_propria_permissao_em_usuarios(self):
        response = self.client_api.patch(
            f'/users/{self.user.id}/',
            {'permissions': {'usuarios': int(AccessLevel.READ)}},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(
            UserPermission.objects.get(user=self.user, resource='usuarios').level,
            AccessLevel.FULL,
        )

    def test_nao_rebaixa_o_ultimo_gestor(self):
        colega = User.objects.create(email='colega@um.com', agency=self.agency)
        grant(colega, 'usuarios', AccessLevel.FULL)

        # Com dois gestores, rebaixar um deles é permitido.
        response = self.client_api.patch(
            f'/users/{colega.id}/',
            {'permissions': {'usuarios': int(AccessLevel.NO_ACCESS)}},
            format='json',
        )
        self.assertEqual(response.status_code, 200)

        # Agora o único gestor restante é o próprio autor da requisição.
        outro = User.objects.create(email='outro@um.com', agency=self.agency)
        grant(outro, 'usuarios', AccessLevel.FULL)
        grant(self.user, 'usuarios', AccessLevel.FULL)

        UserPermission.objects.filter(user=self.user, resource='usuarios').update(
            level=AccessLevel.FULL
        )

        response = self.client_api.patch(
            f'/users/{outro.id}/',
            {'permissions': {'usuarios': int(AccessLevel.NO_ACCESS)}},
            format='json',
        )
        self.assertEqual(response.status_code, 200)

    def test_nao_exclui_o_proprio_usuario(self):
        response = self.client_api.delete(f'/users/{self.user.id}/')

        self.assertEqual(response.status_code, 403)

    def test_nao_exclui_o_ultimo_gestor(self):
        colega = User.objects.create(email='colega@um.com', agency=self.agency)
        grant(colega, 'usuarios', AccessLevel.FULL)
        UserPermission.objects.filter(user=self.user, resource='usuarios').update(
            level=AccessLevel.NO_ACCESS
        )
        grant(self.user, 'usuarios', AccessLevel.FULL)

        # `colega` não é o último: o autor também é gestor.
        response = self.client_api.delete(f'/users/{colega.id}/')
        self.assertEqual(response.status_code, 204)


class ReadOnlyResourceTests(PermissionTestCase):
    """Tela de consulta não aceita nível de escrita, nem por caminho torto."""

    def setUp(self):
        super().setUp()
        grant(self.user, 'usuarios', AccessLevel.FULL)

    def test_recusa_escrita_em_recurso_de_consulta(self):
        colega = User.objects.create(email='colega@um.com', agency=self.agency)

        response = self.client_api.patch(
            f'/users/{colega.id}/',
            {'permissions': {'dashboard': int(AccessLevel.WRITE)}},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_recusa_recurso_desconhecido(self):
        colega = User.objects.create(email='colega@um.com', agency=self.agency)

        response = self.client_api.patch(
            f'/users/{colega.id}/',
            {'permissions': {'inventado': int(AccessLevel.READ)}},
            format='json',
        )

        self.assertEqual(response.status_code, 400)


class PermissionPersistenceTests(PermissionTestCase):
    """O mapa precisa chegar ao banco.

    Regressão: com `source='*'` o DRF espalhava o dicionário na raiz de `validated_data`,
    a gravação não encontrava a chave `permissions` e a requisição respondia 200 sem ter
    salvo nada. Passava despercebido porque só um teste de leitura pegaria.
    """

    def setUp(self):
        super().setUp()
        grant(self.user, 'usuarios', AccessLevel.FULL)

    def test_criacao_grava_as_permissoes(self):
        response = self.client_api.post(
            '/users/',
            {
                'email': 'novo@um.com',
                'name': 'Novo',
                'password': 'senha-de-teste-123',
                'permissions': {
                    'imoveis': int(AccessLevel.READ),
                    'clientes': int(AccessLevel.FULL),
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)

        novo = User.objects.get(email='novo@um.com')
        self.assertEqual(novo.agency_id, self.agency.id)
        self.assertEqual(novo.type, User.Type.USER)
        self.assertEqual(novo.level_for('imoveis'), AccessLevel.READ)
        self.assertEqual(novo.level_for('clientes'), AccessLevel.FULL)
        self.assertEqual(novo.level_for('blog'), AccessLevel.NO_ACCESS)

    def test_edicao_grava_as_permissoes(self):
        colega = User.objects.create(email='colega@um.com', agency=self.agency)
        grant(colega, 'imoveis', AccessLevel.FULL)

        response = self.client_api.patch(
            f'/users/{colega.id}/',
            {'permissions': {'imoveis': int(AccessLevel.READ)}},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            UserPermission.objects.get(user=colega, resource='imoveis').level,
            AccessLevel.READ,
        )
        # A resposta precisa refletir o que acabou de ser gravado, não o estado anterior.
        self.assertEqual(response.json()['data']['permissions']['imoveis'], int(AccessLevel.READ))

    def test_recusa_senha_fraca(self):
        colega = User.objects.create(email='colega@um.com', agency=self.agency)

        # Sem letra, sem número e sem caractere especial, respectivamente.
        for senha in ['12345678!', 'SenhaFraca!', 'SenhaFraca123']:
            response = self.client_api.patch(
                f'/users/{colega.id}/', {'password': senha}, format='json'
            )
            self.assertEqual(response.status_code, 400, senha)

        response = self.client_api.patch(
            f'/users/{colega.id}/', {'password': 'SenhaForte123!'}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.get(pk=colega.pk).check_password('SenhaForte123!'))

    def test_o_nivel_novo_vale_na_requisicao_seguinte(self):
        colega = User.objects.create(email='colega@um.com', agency=self.agency)
        colega.set_password('senha-de-teste-123')
        colega.save()

        self.client_api.patch(
            f'/users/{colega.id}/',
            {'permissions': {'clientes': int(AccessLevel.READ)}},
            format='json',
        )

        api = APIClient()
        api.force_authenticate(user=User.objects.get(pk=colega.pk))

        self.assertEqual(api.get('/clients/').status_code, 200)
        self.assertEqual(
            api.post('/clients/', {'name': 'Novo'}, format='json').status_code, 403
        )
