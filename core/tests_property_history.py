"""Testes do histórico do imóvel e da ficha do proprietário que a listagem imprime."""

import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.models import (
    Agency,
    Broker,
    City,
    Condominium,
    CondominiumPhoto,
    Country,
    Neighborhood,
    Owner,
    Property,
    PropertyHistory,
    PropertyType,
    State,
    User,
    UserPermission,
)
from core.resources import AccessLevel
from core.services.permissions import grant_full_access

TEST_MEDIA_ROOT = tempfile.mkdtemp()

# Teste nunca fala com o S3: mesmo com AWS_* no .env, o arquivo vai para a pasta temporária.
LOCAL_FILE_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def build_image_file(name="foto.png"):
    buffer = BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, format="PNG")

    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, STORAGES=LOCAL_FILE_STORAGES)
class PropertyHistoryTestCase(APITestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = User.objects.create_user(email="corretor@a.com", password="senha123")
        self.user.agency = self.agency
        self.user.name = "Ricardo"
        self.user.save()
        grant_full_access(self.user)

        self.client.force_authenticate(self.user)

    def history_of(self, instance):
        return list(instance.history.all())


class PropertyChangeHistoryTests(PropertyHistoryTestCase):
    def test_cadastro_de_imovel_abre_o_historico(self):
        response = self.client.post("/properties/", {"name": "Casa nova"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        entry = Property.objects.get(name="Casa nova").history.get()
        self.assertEqual(entry.action, PropertyHistory.Action.CREATED)
        self.assertEqual(entry.author_name, "Ricardo")
        self.assertEqual(entry.changes, [])

    def test_edicao_registra_o_que_mudou(self):
        instance = Property.objects.create(agency=self.agency, name="Casa A", bedrooms=2)

        self.client.patch(
            f"/properties/{instance.id}/", {"name": "Casa B", "bedrooms": 3}, format="json"
        )

        entry = instance.history.get(action=PropertyHistory.Action.UPDATED)
        changes = {change["label"]: (change["from"], change["to"]) for change in entry.changes}
        self.assertEqual(changes["Nome"], ("Casa A", "Casa B"))
        self.assertEqual(changes["Quartos"], ("2", "3"))

    def test_edicao_sem_diferenca_nao_vira_linha(self):
        instance = Property.objects.create(agency=self.agency, name="Casa A")

        self.client.patch(f"/properties/{instance.id}/", {"name": "Casa A"}, format="json")

        self.assertFalse(instance.history.filter(action=PropertyHistory.Action.UPDATED).exists())

    def test_troca_de_relacao_registra_o_nome_e_nao_o_id(self):
        instance = Property.objects.create(agency=self.agency, name="Casa A")
        broker = Broker.objects.create(agency=self.agency, name="Maria Santos")

        self.client.patch(
            f"/properties/{instance.id}/", {"broker": str(broker.id)}, format="json"
        )

        entry = instance.history.get(action=PropertyHistory.Action.UPDATED)
        change = next(item for item in entry.changes if item["label"] == "Captador")
        self.assertEqual(change["to"], "Maria Santos")

    def test_mudanca_de_valor_entra_no_historico(self):
        created = self.client.post(
            "/properties/",
            {"name": "Casa A", "prices": [{"purpose": "SALE", "amount": "500000.00"}]},
            format="json",
        ).data["data"]

        self.client.patch(
            f"/properties/{created['id']}/",
            {"prices": [{"purpose": "SALE", "amount": "550000.00"}]},
            format="json",
        )

        entry = Property.objects.get(id=created["id"]).history.get(
            action=PropertyHistory.Action.UPDATED
        )
        change = next(item for item in entry.changes if item["label"] == "Valor de Comprar")
        self.assertEqual((change["from"], change["to"]), ("500000.00", "550000.00"))

    def test_valor_removido_aparece_como_saida(self):
        created = self.client.post(
            "/properties/",
            {"name": "Casa A", "prices": [{"purpose": "RENT", "amount": "3000.00"}]},
            format="json",
        ).data["data"]

        self.client.patch(f"/properties/{created['id']}/", {"prices": []}, format="json")

        entry = Property.objects.get(id=created["id"]).history.get(
            action=PropertyHistory.Action.UPDATED
        )
        change = next(item for item in entry.changes if item["label"] == "Valor de Alugar")
        self.assertEqual((change["from"], change["to"]), ("3000.00", ""))


class PhotoHistoryTests(PropertyHistoryTestCase):
    def setUp(self):
        super().setUp()
        self.property = Property.objects.create(agency=self.agency, name="Casa A")

    def test_upload_registra_inclusao_de_imagens(self):
        self.client.post(
            "/property-photos/",
            {"property": str(self.property.id), "image": build_image_file()},
            format="multipart",
        )

        self.assertTrue(
            self.property.history.filter(action=PropertyHistory.Action.PHOTOS_ADDED).exists()
        )

    def test_exclusao_registra_saida_da_imagem(self):
        photo_id = self.client.post(
            "/property-photos/",
            {"property": str(self.property.id), "image": build_image_file()},
            format="multipart",
        ).data["data"]["id"]

        self.client.delete(f"/property-photos/{photo_id}/")

        self.assertTrue(
            self.property.history.filter(action=PropertyHistory.Action.PHOTOS_REMOVED).exists()
        )

    def test_galeria_de_condominio_nao_gera_historico(self):
        condominium = Condominium.objects.create(agency=self.agency, name="Vila Nova")

        response = self.client.post(
            "/condominium-photos/",
            {"condominium": str(condominium.id), "image": build_image_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(CondominiumPhoto.objects.count(), 1)
        self.assertEqual(PropertyHistory.objects.count(), 0)


class PropertyHistoryEndpointTests(PropertyHistoryTestCase):
    def setUp(self):
        super().setUp()
        self.property = Property.objects.create(agency=self.agency, name="Casa A")

    def test_lista_o_historico_do_imovel(self):
        self.client.patch(f"/properties/{self.property.id}/", {"name": "Casa B"}, format="json")

        response = self.client.get(f"/properties/{self.property.id}/history/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entry = response.json()["data"][0]
        self.assertEqual(entry["action"], "UPDATED")
        self.assertEqual(entry["action_label"], "Alteração do imóvel")
        self.assertEqual(entry["author_name"], "Ricardo")

    def test_historico_de_outro_imovel_nao_vaza(self):
        other = Property.objects.create(agency=self.agency, name="Casa C")
        PropertyHistory.objects.create(
            property=other, action=PropertyHistory.Action.CREATED, author_name="Outro"
        )

        response = self.client.get(f"/properties/{self.property.id}/history/")

        self.assertEqual(response.json()["data"], [])

    def test_imovel_de_outra_imobiliaria_nao_tem_historico_visivel(self):
        outside = Property.objects.create(agency=self.other_agency, name="Casa de outra")

        response = self.client.get(f"/properties/{outside.id}/history/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_sem_autenticacao_devolve_401(self):
        self.client.force_authenticate(None)

        response = self.client.get(f"/properties/{self.property.id}/history/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_leitura_em_imoveis_basta_para_ver_o_historico(self):
        reader = User.objects.create_user(email="leitor@a.com", password="senha123")
        reader.agency = self.agency
        reader.save()
        UserPermission.objects.create(user=reader, resource="imoveis", level=AccessLevel.READ)
        self.client.force_authenticate(reader)

        response = self.client.get(f"/properties/{self.property.id}/history/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_sem_permissao_em_imoveis_devolve_403(self):
        outsider = User.objects.create_user(email="sem@a.com", password="senha123")
        outsider.agency = self.agency
        outsider.save()
        self.client.force_authenticate(outsider)

        response = self.client.get(f"/properties/{self.property.id}/history/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class OwnerCardTests(PropertyHistoryTestCase):
    def test_imovel_traz_a_ficha_do_proprietario(self):
        owner = Owner.objects.create(
            agency=self.agency,
            name="Paulo Ramos",
            spouse="Marta Ramos",
            document="123.456.789-09",
            mobile="(24) 98142-9044",
            business_phone="(24) 2222-5083",
            notes="Prefere contato à tarde.",
        )
        instance = Property.objects.create(
            agency=self.agency, name="Casa A", type=PropertyType.objects.create(name="Casa"), owner=owner
        )

        response = self.client.get(f"/properties/{instance.id}/")

        data = response.json()["data"]["owner_data"]
        self.assertEqual(data["name"], "Paulo Ramos")
        self.assertEqual(data["spouse"], "Marta Ramos")
        self.assertEqual(data["document"], "123.456.789-09")
        self.assertEqual(data["mobile"], "(24) 98142-9044")
        self.assertEqual(data["business_phone"], "(24) 2222-5083")
        self.assertEqual(data["notes"], "Prefere contato à tarde.")

    def test_imovel_sem_proprietario_traz_a_ficha_vazia(self):
        instance = Property.objects.create(agency=self.agency, name="Casa A")

        response = self.client.get(f"/properties/{instance.id}/")

        self.assertIsNone(response.json()["data"]["owner_data"])

    def test_cadastro_de_proprietario_grava_os_campos_novos(self):
        response = self.client.post(
            "/owners/",
            {
                "name": "Helena Vasconcelos",
                "spouse": "Jorge Vasconcelos",
                "document": "987.654.321-00",
                "birth_date": "1975-03-22",
                "mobile": "(24) 99999-1234",
                "notes": "Dois imóveis na serra.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        owner = Owner.objects.get(name="Helena Vasconcelos")
        self.assertEqual(owner.spouse, "Jorge Vasconcelos")
        self.assertEqual(str(owner.birth_date), "1975-03-22")
        self.assertEqual(owner.notes, "Dois imóveis na serra.")


class OwnerCardQueryCountTests(PropertyHistoryTestCase):
    """A ficha do proprietário vem junto na listagem, então ela não pode custar por imóvel."""

    def setUp(self):
        super().setUp()
        country = Country.objects.create(name="Brasil", code="BRA")
        state = State.objects.create(country=country, name="Rio de Janeiro", abbreviation="RJ")
        city = City.objects.create(state=state, name="Petrópolis", ibge_code="3303906")
        self.neighborhood = Neighborhood.objects.create(city=city, name="Centro")

    def build(self, quantity):
        for index in range(quantity):
            owner = Owner.objects.create(
                agency=self.agency, name=f"Dono {index}", neighborhood=self.neighborhood
            )
            Property.objects.create(
                agency=self.agency, name=f"Casa {index}", code=str(index), owner=owner
            )

    def count_queries(self):
        with CaptureQueriesContext(connection) as captured:
            self.client.get("/properties/")

        return len(captured)

    def test_listagem_nao_consulta_uma_vez_por_imovel(self):
        self.build(2)
        few = self.count_queries()

        # O imóvel sai primeiro: Property.owner é PROTECT.
        Property.objects.all().delete()
        Owner.objects.all().delete()
        self.build(12)

        # Seis vezes mais imóveis não pode custar nenhuma consulta a mais.
        self.assertLessEqual(self.count_queries(), few)
