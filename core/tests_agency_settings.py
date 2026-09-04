"""Testes das configurações da imobiliária (registro único por conta)."""

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Agency, AgencySettings, User, UserPermission
from core.resources import AccessLevel

ENDPOINT = '/agency-settings/'


def grant(user, resource, level):
    UserPermission.objects.update_or_create(
        user=user, resource=resource, defaults={'level': level}
    )


class AgencySettingsTestCase(TestCase):
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


class AccessTests(AgencySettingsTestCase):
    def test_sem_autenticacao_devolve_401(self):
        self.assertEqual(APIClient().get(ENDPOINT).status_code, 401)

    def test_sem_permissao_devolve_403(self):
        self.assertEqual(self.client_api.get(ENDPOINT).status_code, 403)

    def test_leitura_le_mas_nao_salva(self):
        grant(self.user, 'configuracoes', AccessLevel.READ)

        self.assertEqual(self.client_api.get(ENDPOINT).status_code, 200)

        response = self.client_api.patch(ENDPOINT, {'system_name': 'Novo'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_admin_da_plataforma_sem_imobiliaria_devolve_400(self):
        admin = User.objects.create(email='admin@plataforma.com', type=User.Type.ADMIN)
        api = APIClient()
        api.force_authenticate(user=admin)

        self.assertEqual(api.get(ENDPOINT).status_code, 400)


class SingletonTests(AgencySettingsTestCase):
    def test_get_cria_um_unico_registro_por_imobiliaria(self):
        grant(self.user, 'configuracoes', AccessLevel.READ)

        self.client_api.get(ENDPOINT)
        self.client_api.get(ENDPOINT)

        self.assertEqual(AgencySettings.objects.filter(agency=self.agency).count(), 1)

    def test_patch_salva_no_registro_da_imobiliaria(self):
        grant(self.user, 'configuracoes', AccessLevel.WRITE)

        response = self.client_api.patch(
            ENDPOINT,
            {'system_name': 'Imobiliária Um', 'instagram_url': 'https://instagram.com/um'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        settings = AgencySettings.objects.get(agency=self.agency)
        self.assertEqual(settings.system_name, 'Imobiliária Um')
        self.assertEqual(settings.instagram_url, 'https://instagram.com/um')

    def test_dado_invalido_devolve_400_com_o_campo(self):
        grant(self.user, 'configuracoes', AccessLevel.WRITE)

        response = self.client_api.patch(
            ENDPOINT, {'primary_color': 'verde'}, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0]['field'], 'primary_color')


class TenantIsolationTests(AgencySettingsTestCase):
    def test_cada_imobiliaria_enxerga_o_proprio_registro(self):
        grant(self.user, 'configuracoes', AccessLevel.WRITE)
        grant(self.other_user, 'configuracoes', AccessLevel.READ)

        self.client_api.patch(ENDPOINT, {'system_name': 'Da Um'}, format='json')

        other_api = APIClient()
        other_api.force_authenticate(user=self.other_user)
        response = other_api.get(ENDPOINT)

        self.assertEqual(response.json()['data']['system_name'], '')

    def test_imobiliaria_nao_vem_do_payload(self):
        grant(self.user, 'configuracoes', AccessLevel.WRITE)

        self.client_api.patch(
            ENDPOINT,
            {'system_name': 'Da Um', 'agency': str(self.other_agency.id)},
            format='json',
        )

        settings = AgencySettings.objects.get(system_name='Da Um')
        self.assertEqual(settings.agency_id, self.agency.id)
        self.assertFalse(AgencySettings.objects.filter(agency=self.other_agency).exists())
