from rest_framework import status
from rest_framework.test import APITestCase

from core.models import (
    Agency,
    Country,
    Exporter,
    ExporterPlan,
    Feature,
    PropertyType,
    State,
    User,
)


class AdminWebAccessTests(APITestCase):
    """Todo recurso do painel administrativo tem a mesma regra: só usuário ADMIN entra."""

    # Um por recurso registrado em admin_web/urls.py.
    ENDPOINTS = [
        "/admin-web/agencies/",
        "/admin-web/plans/",
        "/admin-web/users/",
        "/admin-web/property-types/",
        "/admin-web/features/",
        "/admin-web/fees/",
        "/admin-web/exporters/",
        "/admin-web/exporter-plans/",
        "/admin-web/countries/",
        "/admin-web/states/",
        "/admin-web/cities/",
        "/admin-web/neighborhoods/",
    ]

    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")

        self.user = User.objects.create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        self.admin = User.objects.create_user(email="admin@teste.com", password="senha123")
        self.admin.type = User.Type.ADMIN
        self.admin.save()

    def test_sem_autenticacao_nenhum_recurso_responde(self):
        for endpoint in self.ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint)

                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_usuario_comum_nao_entra_em_nenhum_recurso(self):
        self.client.force_authenticate(self.user)

        for endpoint in self.ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint)

                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_entra_em_todos_os_recursos(self):
        self.client.force_authenticate(self.admin)

        for endpoint in self.ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint)

                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_usuario_comum_nao_cria_registro(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/admin-web/property-types/", {"name": "Sítio"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(PropertyType.objects.filter(name="Sítio").exists())


class AdminWebAgencyTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="admin@teste.com", password="senha123")
        self.admin.type = User.Type.ADMIN
        self.admin.save()

        self.client.force_authenticate(self.admin)

    def test_cria_imobiliaria_e_gera_o_slug(self):
        response = self.client.post(
            "/admin-web/agencies/", {"name": "Imobiliária Central"}, format="json"
        )

        agency = Agency.objects.get(name="Imobiliária Central")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(agency.slug, "imobiliaria-central")

    def test_nome_repetido_devolve_erro_de_validacao(self):
        Agency.objects.create(name="Imobiliária Central")

        response = self.client.post(
            "/admin-web/agencies/", {"name": "Imobiliária Central"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Agency.objects.filter(name="Imobiliária Central").count(), 1)

    def test_renomear_imobiliaria_preserva_o_slug(self):
        agency = Agency.objects.create(name="Imobiliária Central")

        response = self.client.patch(
            f"/admin-web/agencies/{agency.id}/", {"name": "Central Imóveis"}, format="json"
        )

        agency.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(agency.slug, "imobiliaria-central")

    def test_excluir_imobiliaria_some_da_listagem(self):
        agency = Agency.objects.create(name="Imobiliária Central")

        response = self.client.delete(f"/admin-web/agencies/{agency.id}/")

        agency.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIsNotNone(agency.deleted_at)
        self.assertEqual(self.client.get("/admin-web/agencies/").data["data"]["count"], 0)


class AdminWebUserTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")

        self.admin = User.objects.create_user(email="admin@teste.com", password="senha123")
        self.admin.type = User.Type.ADMIN
        self.admin.save()

        self.client.force_authenticate(self.admin)

    def test_cria_usuario_com_imobiliaria_e_perfil(self):
        response = self.client.post(
            "/admin-web/users/",
            {
                "email": "novo@teste.com",
                "name": "Novo",
                "agency": str(self.agency.id),
                "type": User.Type.USER,
                "password": "SenhaForte123",
            },
            format="json",
        )

        user = User.objects.get(email="novo@teste.com")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(user.agency_id, self.agency.id)
        self.assertEqual(user.type, User.Type.USER)
        self.assertTrue(user.check_password("SenhaForte123"))

    def test_senha_nunca_volta_na_resposta(self):
        response = self.client.post(
            "/admin-web/users/",
            {"email": "novo@teste.com", "password": "SenhaForte123"},
            format="json",
        )

        self.assertNotIn("password", response.data["data"])

    def test_usuario_sem_senha_e_recusado(self):
        response = self.client.post(
            "/admin-web/users/", {"email": "novo@teste.com"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email="novo@teste.com").exists())

    def test_senha_fraca_e_recusada(self):
        response = self.client.post(
            "/admin-web/users/",
            {"email": "novo@teste.com", "password": "123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email="novo@teste.com").exists())

    def test_admin_redefine_a_senha_sem_a_senha_atual(self):
        user = User.objects.create_user(email="alvo@teste.com", password="senha123")

        response = self.client.patch(
            f"/admin-web/users/{user.id}/", {"password": "OutraSenha456"}, format="json"
        )

        user.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(user.check_password("OutraSenha456"))


class AdminWebCatalogTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="admin@teste.com", password="senha123")
        self.admin.type = User.Type.ADMIN
        self.admin.save()

        self.client.force_authenticate(self.admin)

    def test_cria_infraestrutura_de_condominio(self):
        response = self.client.post(
            "/admin-web/features/",
            {"name": "Salão de festas", "type": Feature.Type.CONDOMINIUM},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Feature.objects.get(name="Salão de festas").type, Feature.Type.CONDOMINIUM
        )

    def test_filtra_estado_por_pais(self):
        brasil = Country.objects.create(name="Brasil", code="BRA")
        portugal = Country.objects.create(name="Portugal", code="PRT")
        State.objects.create(country=brasil, name="Rio de Janeiro", abbreviation="RJ")
        State.objects.create(country=portugal, name="Lisboa", abbreviation="LIS")

        response = self.client.get(f"/admin-web/states/?country={brasil.id}")

        names = [item["name"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(names, ["Rio de Janeiro"])

    def test_cria_exportador_e_gera_o_identificador(self):
        # O formulário do painel manda o campo vazio quando o administrador não preenche.
        response = self.client.post(
            "/admin-web/exporters/", {"name": "Portal Imóveis Já", "slug": ""}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Exporter.objects.get(name="Portal Imóveis Já").slug, "portal-imoveis-ja")

    def test_identificador_informado_e_mantido(self):
        response = self.client.post(
            "/admin-web/exporters/",
            {"name": "Portal Novo", "slug": "portal-parceiro"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Exporter.objects.get(name="Portal Novo").slug, "portal-parceiro")

    def test_identificador_repetido_e_recusado(self):
        Exporter.objects.create(name="Portal Um", slug="portal")

        response = self.client.post(
            "/admin-web/exporters/",
            {"name": "Portal Dois", "slug": "portal"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Exporter.objects.filter(name="Portal Dois").exists())

    def test_nomes_diferentes_com_o_mesmo_identificador_sao_recusados(self):
        Exporter.objects.create(name="Portal ABC")

        # O nome passa na unicidade, mas os dois viram o mesmo slug.
        response = self.client.post(
            "/admin-web/exporters/", {"name": "Portal-ABC"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Exporter.objects.filter(slug="portal-abc").count(), 1)

    def test_renomear_exportador_preserva_o_identificador(self):
        exporter = Exporter.objects.create(name="Portal Antigo")

        response = self.client.patch(
            f"/admin-web/exporters/{exporter.id}/", {"name": "Portal Novo"}, format="json"
        )

        exporter.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(exporter.slug, "portal-antigo")

    def test_exclui_plano_de_exportador(self):
        exporter = Exporter.objects.create(name="Portal X")
        plan = ExporterPlan.objects.create(exporter=exporter, name="Básico")

        response = self.client.delete(f"/admin-web/exporter-plans/{plan.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ExporterPlan.objects.filter(id=plan.id).exists())
