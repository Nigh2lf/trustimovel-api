import json
import shutil
import tempfile
from io import BytesIO
from pathlib import PurePosixPath
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import (
    Agency,
    AgencyExporter,
    AgencyExporterPlan,
    BlogCategory,
    BlogPost,
    Broker,
    City,
    Client,
    CompanySection,
    Condominium,
    CondominiumPhoto,
    Country,
    Exporter,
    ExporterPlan,
    Feature,
    Fee,
    Neighborhood,
    Owner,
    Plan,
    Property,
    PropertyExporter,
    PropertyFee,
    PropertyPhoto,
    PropertyPrice,
    PropertyType,
    SiteBanner,
    State,
    User,
)
from core.services.address import AddressLookupError, find_or_create_address
from core.services.permissions import grant_full_access
from core.services.photos import thumbnail_name


TEST_MEDIA_ROOT = tempfile.mkdtemp()

# Teste nunca fala com o S3: mesmo com AWS_* no .env, o arquivo vai para a pasta temporária.
LOCAL_FILE_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def create_user(**kwargs):
    """Usuário de teste já com acesso a todos os recursos.

    Esta suíte exercita regra de negócio e isolamento entre imobiliárias, não o
    permissionamento — esse tem arquivo próprio em `tests_permissions.py`. Sem a concessão,
    toda requisição pararia em 403 antes de alcançar a regra sob teste.
    """
    user = User.objects.create_user(**kwargs)
    grant_full_access(user)

    return user


def build_image_file(name="foto.png", size=(1, 1)):
    buffer = BytesIO()
    Image.new("RGB", size).save(buffer, format="PNG")

    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, STORAGES=LOCAL_FILE_STORAGES)
class MediaTestCase(APITestCase):
    """Base de todo teste que grava arquivo: o media vai para uma pasta temporária."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()


class LoginTests(APITestCase):
    def setUp(self):
        self.user = create_user(email="usuario@teste.com", password="senha123")

    def test_login_com_credenciais_corretas_retorna_tokens(self):
        response = self.client.post(
            "/auth-user/",
            {"email": "usuario@teste.com", "password": "senha123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertIn("access", response.data["data"])
        self.assertIn("refresh", response.data["data"])
        self.assertEqual(response.data["data"]["user"]["email"], "usuario@teste.com")

    def test_login_com_senha_incorreta_e_generico(self):
        response = self.client.post(
            "/auth-user/",
            {"email": "usuario@teste.com", "password": "senha_errada"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["status"], "error")

    def test_login_com_email_inexistente_retorna_a_mesma_mensagem_que_senha_incorreta(self):
        # Garante que a mensagem não permite descobrir se um e-mail está cadastrado.
        response = self.client.post(
            "/auth-user/",
            {"email": "naoexiste@teste.com", "password": "qualquer"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["message"], "E-mail ou senha inválidos.")


class UserViewSetPermissionTests(APITestCase):
    """Quem gerencia usuários é quem tem o recurso `usuarios`, não mais só o ADMIN."""

    def setUp(self):
        self.admin = User.objects.create_user(email="admin@teste.com", password="senha123")
        self.admin.type = "ADMIN"
        self.admin.save()

        # Sem concessão, de propósito: aqui o assunto é justamente a falta de permissão.
        self.usuario = User.objects.create_user(email="usuario@teste.com", password="senha123")
        self.outro_usuario = User.objects.create_user(email="outro@teste.com", password="senha123")

    def test_listar_usuarios_sem_autenticacao_falha(self):
        response = self.client.get("/users/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_usuario_sem_permissao_nao_pode_listar_usuarios(self):
        self.client.force_authenticate(self.usuario)

        response = self.client.get("/users/")

        # 403 e não 401: a sessão é válida, o que falta é permissão. O painel avisa em
        # vez de deslogar.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_usuario_sem_permissao_nao_pode_ler_dado_de_outro_usuario(self):
        self.client.force_authenticate(self.usuario)

        response = self.client.get(f"/users/{self.outro_usuario.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_usuario_sem_permissao_nao_pode_editar_outro_usuario(self):
        self.client.force_authenticate(self.usuario)

        response = self.client.patch(
            f"/users/{self.outro_usuario.id}/", {"name": "Hackeado"}, format="json"
        )

        self.outro_usuario.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotEqual(self.outro_usuario.name, "Hackeado")

    def test_usuario_com_o_recurso_gerencia_a_equipe(self):
        grant_full_access(self.usuario)
        self.client.force_authenticate(self.usuario)

        response = self.client.get(f"/users/{self.outro_usuario.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_pode_gerenciar_usuarios(self):
        self.client.force_authenticate(self.admin)

        response = self.client.get(f"/users/{self.usuario.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_campo_privilegiado_enviado_no_payload_e_ignorado(self):
        self.client.force_authenticate(self.admin)

        # `is_admin` não existe no serializer e cai fora em silêncio.
        response = self.client.patch(
            f"/users/{self.usuario.id}/", {"is_admin": True}, format="json"
        )

        self.usuario.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(self.usuario.is_admin)

    def test_tipo_admin_da_plataforma_nao_e_aceito_no_payload(self):
        # `type` aceita só os perfis da imobiliária (USER e BROKER): promover a ADMIN é recusado.
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            f"/users/{self.usuario.id}/", {"type": "ADMIN"}, format="json"
        )

        self.usuario.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.usuario.type, "USER")

    def test_desativar_usuario_e_permitido(self):
        # `is_active` saiu dos read_only: desativar é o caminho normal para tirar o acesso
        # de quem deixou a imobiliária, sem apagar o histórico da pessoa.
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            f"/users/{self.usuario.id}/", {"is_active": False}, format="json"
        )

        self.usuario.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(self.usuario.is_active)


class ForgotPasswordTests(APITestCase):
    def setUp(self):
        self.user = create_user(email="usuario@teste.com", password="senha123")

    @patch("core.views.user.send_email_forgot_password")
    def test_email_cadastrado_e_nao_cadastrado_retornam_a_mesma_resposta(self, mock_send_email):
        response_existente = self.client.post(
            "/users/forgot-password/", {"email": "usuario@teste.com"}, format="json"
        )
        response_inexistente = self.client.post(
            "/users/forgot-password/", {"email": "naoexiste@teste.com"}, format="json"
        )

        self.assertEqual(response_existente.status_code, response_inexistente.status_code)
        self.assertEqual(response_existente.data, response_inexistente.data)
        mock_send_email.assert_called_once()


class PropertyTenantIsolationTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        self.property = Property.objects.create(agency=self.agency, name="Casa A")
        self.other_property = Property.objects.create(agency=self.other_agency, name="Casa B")
        # A migration do catálogo já cria as taxas padrão no banco de teste.
        self.condominium_fee, _ = Fee.objects.get_or_create(name="Condomínio")

    def test_listagem_retorna_apenas_imoveis_da_propria_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/properties/")

        names = [item["name"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(names, ["Casa A"])

    def test_nao_acessa_imovel_de_outra_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(f"/properties/{self.other_property.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_nao_edita_imovel_de_outra_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            f"/properties/{self.other_property.id}/", {"name": "Invadido"}, format="json"
        )

        self.other_property.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.other_property.name, "Casa B")

    def test_listagem_sem_autenticacao_falha(self):
        response = self.client.get("/properties/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_imovel_criado_recebe_a_imobiliaria_do_usuario(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/",
            {
                "name": "Casa nova",
                "prices": [{"purpose": "SALE", "amount": "500000.00", "notes": ""}],
                "fees": [{"fee": str(self.condominium_fee.id), "amount": "800.00", "notes": ""}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = Property.objects.get(name="Casa nova")
        self.assertEqual(created.agency, self.agency)
        self.assertEqual(created.prices.count(), 1)
        self.assertEqual(created.fees.count(), 1)

    def test_nao_vincula_condominio_de_outra_imobiliaria(self):
        other_condominium = Condominium.objects.create(
            agency=self.other_agency, name="Condomínio B"
        )
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/",
            {"name": "Casa X", "condominium": str(other_condominium.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_imovel_aceita_venda_e_locacao_simultaneas(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/",
            {
                "name": "Casa dupla",
                "prices": [
                    {"purpose": "SALE", "amount": "900000.00", "notes": ""},
                    {"purpose": "RENT", "amount": "4500.00", "notes": ""},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = Property.objects.get(name="Casa dupla")
        self.assertEqual(
            sorted(created.prices.values_list("purpose", flat=True)), ["RENT", "SALE"]
        )


class PropertyPhotoTests(MediaTestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        self.property = Property.objects.create(agency=self.agency, name="Casa A")
        self.other_property = Property.objects.create(agency=self.other_agency, name="Casa B")

    def test_upload_de_foto_sem_autenticacao_falha(self):
        response = self.client.post(
            "/property-photos/",
            {"property": str(self.property.id), "image": build_image_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(PropertyPhoto.objects.count(), 0)

    def test_envia_foto_para_imovel_da_propria_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/property-photos/",
            {"property": str(self.property.id), "image": build_image_file(), "is_main": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.property.photos.count(), 1)

    def test_foto_e_salva_na_pasta_da_imobiliaria_com_nome_proprio(self):
        self.client.force_authenticate(self.user)

        self.client.post(
            "/property-photos/",
            {"property": str(self.property.id), "image": build_image_file("../../invasao.png")},
            format="multipart",
        )

        photo = self.property.photos.get()
        self.assertTrue(photo.image.name.startswith(f"photos/{self.agency.slug}/property-"))
        # O nome enviado pelo cliente é descartado, então não dá para escapar da pasta.
        self.assertNotIn("invasao", photo.image.name)
        self.assertNotIn("..", photo.image.name)
        self.assertTrue(photo.image.name.endswith(".webp"))

    def test_recusa_arquivo_com_extensao_nao_aceita(self):
        self.client.force_authenticate(self.user)
        arquivo = SimpleUploadedFile("contrato.pdf", b"%PDF-1.4 fake", content_type="application/pdf")

        response = self.client.post(
            "/property-photos/",
            {"property": str(self.property.id), "image": arquivo},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PropertyPhoto.objects.count(), 0)

    def test_nao_envia_foto_para_imovel_de_outra_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/property-photos/",
            {"property": str(self.other_property.id), "image": build_image_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PropertyPhoto.objects.count(), 0)

    def test_listagem_retorna_apenas_fotos_da_propria_imobiliaria(self):
        PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        other_photo = PropertyPhoto.objects.create(
            property=self.other_property, image=build_image_file()
        )
        self.client.force_authenticate(self.user)

        response = self.client.get("/property-photos/")

        ids = [item["id"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(str(other_photo.id), ids)
        self.assertEqual(len(ids), 1)

    def test_exclui_foto_do_proprio_imovel(self):
        photo = PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        self.client.force_authenticate(self.user)

        response = self.client.delete(f"/property-photos/{photo.id}/")

        photo.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIsNotNone(photo.deleted_at)

    def test_excluir_foto_apaga_o_arquivo_da_pasta(self):
        self.client.force_authenticate(self.user)
        self._upload()

        photo = self.property.photos.get()
        storage = photo.image.storage
        arquivo = photo.image.name
        mini = thumbnail_name(arquivo)
        self.assertTrue(storage.exists(arquivo))
        self.assertTrue(storage.exists(mini))

        self.client.delete(f"/property-photos/{photo.id}/")

        self.assertFalse(storage.exists(arquivo))
        self.assertFalse(storage.exists(mini))

    def test_excluir_a_principal_promove_a_primeira_da_lista(self):
        self.client.force_authenticate(self.user)
        self._upload(name="primeira.png")
        self._upload(name="segunda.png")
        self._upload(name="terceira.png")

        primeira, segunda, _terceira = list(self.property.photos.order_by("position"))
        self.assertTrue(primeira.is_main)

        self.client.delete(f"/property-photos/{primeira.id}/")

        segunda.refresh_from_db()
        self.assertTrue(segunda.is_main)
        self.assertTrue(segunda.image.storage.exists(thumbnail_name(segunda.image.name)))

    def test_excluir_a_unica_foto_deixa_o_imovel_sem_miniatura(self):
        self.client.force_authenticate(self.user)
        self._upload()

        photo = self.property.photos.get()
        response = self.client.delete(f"/property-photos/{photo.id}/")

        photo.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(photo.is_main)
        self.assertEqual(self.property.photos.filter(deleted_at__isnull=True).count(), 0)

    def test_remove_todas_as_fotos_do_imovel(self):
        self.client.force_authenticate(self.user)
        self._upload(name="a.png")
        self._upload(name="b.png")

        photos = list(self.property.photos.all())
        storage = photos[0].image.storage
        arquivos = [photo.image.name for photo in photos]

        response = self.client.post(
            "/property-photos/delete-all/", {"property": str(self.property.id)}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["deleted"], 2)
        self.assertEqual(self.property.photos.filter(deleted_at__isnull=True).count(), 0)

        for arquivo in arquivos:
            self.assertFalse(storage.exists(arquivo))
            self.assertFalse(storage.exists(thumbnail_name(arquivo)))

    def test_nao_remove_todas_as_fotos_de_imovel_de_outra_imobiliaria(self):
        alheia = PropertyPhoto.objects.create(
            property=self.other_property, image=build_image_file()
        )
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/property-photos/delete-all/",
            {"property": str(self.other_property.id)},
            format="json",
        )

        alheia.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNone(alheia.deleted_at)

    def test_foto_excluida_some_das_telas_mas_continua_no_banco(self):
        photo = PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        self.client.force_authenticate(self.user)

        self.client.delete(f"/property-photos/{photo.id}/")

        photo.refresh_from_db()
        self.assertIsNotNone(photo.deleted_at)
        self.assertEqual(self.client.get("/property-photos/").data["data"]["count"], 0)

        imovel = self.client.get(f"/properties/{self.property.id}/").data["data"]
        self.assertEqual(imovel["photos"], [])

    def test_filtro_de_fotos_ignora_as_excluidas(self):
        photo = PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        photo.delete()
        self.client.force_authenticate(self.user)

        response = self.client.get("/properties/?has_photos=true")

        self.assertEqual(response.data["data"]["count"], 0)

    def test_nao_reordena_foto_excluida(self):
        ativa = PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        excluida = PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        excluida.delete()
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/property-photos/reorder/",
            {"photos": [str(excluida.id), str(ativa.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nao_exclui_foto_de_outra_imobiliaria(self):
        other_photo = PropertyPhoto.objects.create(
            property=self.other_property, image=build_image_file()
        )
        self.client.force_authenticate(self.user)

        response = self.client.delete(f"/property-photos/{other_photo.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(PropertyPhoto.objects.filter(id=other_photo.id).exists())

    def _upload(self, size=(1, 1), name="foto.png", is_main=None):
        payload = {"property": str(self.property.id), "image": build_image_file(name, size)}

        if is_main is not None:
            payload["is_main"] = is_main

        return self.client.post("/property-photos/", payload, format="multipart")

    def test_reduz_a_imagem_pelo_maior_lado(self):
        self.client.force_authenticate(self.user)

        self._upload(size=(2400, 1600))

        photo = self.property.photos.get()
        with Image.open(photo.image) as saved:
            self.assertEqual(max(saved.size), 1200)
            # A proporção original é preservada.
            self.assertEqual(saved.size, (1200, 800))

    @override_settings(PROPERTY_PHOTO_MAX_SIDE=600, PROPERTY_PHOTO_THUMBNAIL_SIDE=200)
    def test_limites_vem_das_configuracoes(self):
        self.client.force_authenticate(self.user)

        self._upload(size=(2400, 1600))

        photo = self.property.photos.get()
        with Image.open(photo.image) as saved:
            self.assertEqual(max(saved.size), 600)

        storage = photo.image.storage
        with storage.open(thumbnail_name(photo.image.name)) as arquivo:
            with Image.open(arquivo) as mini:
                self.assertEqual(max(mini.size), 200)

    @override_settings(PROPERTY_PHOTO_MAX_PER_PROPERTY=2)
    def test_recusa_foto_acima_do_limite_do_imovel(self):
        self.client.force_authenticate(self.user)

        self.assertEqual(self._upload().status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._upload().status_code, status.HTTP_201_CREATED)
        response = self._upload()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.property.photos.count(), 2)

    @override_settings(PROPERTY_PHOTO_MAX_PER_PROPERTY=2)
    def test_foto_excluida_libera_vaga_no_limite(self):
        self.client.force_authenticate(self.user)
        self._upload()
        self._upload()

        self.property.photos.first().delete()

        self.assertEqual(self._upload().status_code, status.HTTP_201_CREATED)

    @override_settings(PROPERTY_PHOTO_MAX_UPLOAD_MB=0)
    def test_limite_de_tamanho_vem_das_configuracoes(self):
        self.client.force_authenticate(self.user)

        response = self._upload(size=(50, 50))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_imagem_menor_que_o_limite_nao_e_ampliada(self):
        self.client.force_authenticate(self.user)

        self._upload(size=(300, 200))

        with Image.open(self.property.photos.get().image) as saved:
            self.assertEqual(saved.size, (300, 200))

    def test_primeira_foto_vira_miniatura_e_gera_o_arquivo_mini(self):
        self.client.force_authenticate(self.user)

        self._upload(size=(2000, 1000))

        photo = self.property.photos.get()
        mini = thumbnail_name(photo.image.name)
        self.assertTrue(photo.is_main)
        self.assertEqual(PurePosixPath(mini).name, f"mini-{PurePosixPath(photo.image.name).name}")
        self.assertTrue(photo.image.storage.exists(mini))

        with photo.image.storage.open(mini) as arquivo, Image.open(arquivo) as imagem:
            self.assertEqual(max(imagem.size), 500)

    def test_trocar_miniatura_apaga_a_mini_anterior(self):
        self.client.force_authenticate(self.user)
        self._upload(size=(800, 600), name="primeira.png")
        self._upload(size=(800, 600), name="segunda.png")

        primeira, segunda = list(self.property.photos.order_by("position"))
        mini_antiga = thumbnail_name(primeira.image.name)
        storage = primeira.image.storage
        self.assertTrue(storage.exists(mini_antiga))

        self.client.patch(f"/property-photos/{segunda.id}/", {"is_main": True}, format="json")

        primeira.refresh_from_db()
        segunda.refresh_from_db()
        self.assertFalse(primeira.is_main)
        self.assertTrue(segunda.is_main)
        self.assertFalse(storage.exists(mini_antiga))
        self.assertTrue(storage.exists(thumbnail_name(segunda.image.name)))

    def test_foto_guarda_o_tamanho_do_arquivo(self):
        self.client.force_authenticate(self.user)

        self._upload(size=(400, 300))

        photo = self.property.photos.get()
        # O tamanho gravado é o do arquivo convertido, não o do enviado.
        self.assertEqual(photo.file_size, photo.image.size)
        self.assertGreater(photo.file_size, 0)

    def test_converte_a_foto_enviada_para_webp(self):
        self.client.force_authenticate(self.user)

        self._upload(size=(900, 600), name="foto.png")

        photo = self.property.photos.get()
        self.assertTrue(photo.image.name.endswith(".webp"))

        with Image.open(photo.image) as saved:
            self.assertEqual(saved.format, "WEBP")

        storage = photo.image.storage
        mini = thumbnail_name(photo.image.name)
        self.assertTrue(mini.endswith(".webp"))

        with storage.open(mini) as arquivo, Image.open(arquivo) as imagem:
            self.assertEqual(imagem.format, "WEBP")

    def test_fotos_recebem_posicao_sequencial(self):
        primeira = PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        segunda = PropertyPhoto.objects.create(property=self.property, image=build_image_file())

        self.assertEqual([primeira.position, segunda.position], [1, 2])

    def test_reordena_fotos_do_imovel(self):
        primeira = PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        segunda = PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/property-photos/reorder/",
            {"photos": [str(segunda.id), str(primeira.id)]},
            format="json",
        )

        primeira.refresh_from_db()
        segunda.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([segunda.position, primeira.position], [1, 2])
        self.assertEqual(
            list(self.property.photos.values_list("id", flat=True)), [segunda.id, primeira.id]
        )

    def test_nao_reordena_incluindo_foto_de_outra_imobiliaria(self):
        propria = PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        alheia = PropertyPhoto.objects.create(
            property=self.other_property, image=build_image_file(), position=7
        )
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/property-photos/reorder/",
            {"photos": [str(alheia.id), str(propria.id)]},
            format="json",
        )

        alheia.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(alheia.position, 7)

    def test_define_outra_foto_como_miniatura(self):
        capa = PropertyPhoto.objects.create(
            property=self.property, image=build_image_file(), is_main=True
        )
        outra = PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            f"/property-photos/{outra.id}/", {"is_main": True}, format="json"
        )

        capa.refresh_from_db()
        outra.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(outra.is_main)
        self.assertFalse(capa.is_main)

    def test_nova_foto_principal_desmarca_a_anterior(self):
        first_photo = PropertyPhoto.objects.create(
            property=self.property, image=build_image_file(), is_main=True
        )
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/property-photos/",
            {"property": str(self.property.id), "image": build_image_file(), "is_main": True},
            format="multipart",
        )

        first_photo.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(first_photo.is_main)
        self.assertEqual(self.property.photos.filter(is_main=True).count(), 1)

    def test_imovel_retorna_as_fotos_na_listagem(self):
        PropertyPhoto.objects.create(property=self.property, image=build_image_file())
        self.client.force_authenticate(self.user)

        response = self.client.get(f"/properties/{self.property.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]["photos"]), 1)


class CondominiumPhotoTests(MediaTestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        self.condominium = Condominium.objects.create(agency=self.agency, name="Condomínio A")
        self.other_condominium = Condominium.objects.create(
            agency=self.other_agency, name="Condomínio B"
        )

    def _upload(self, name="foto.png", size=(1, 1)):
        return self.client.post(
            "/condominium-photos/",
            {"condominium": str(self.condominium.id), "image": build_image_file(name, size)},
            format="multipart",
        )

    def test_upload_de_foto_sem_autenticacao_falha(self):
        response = self._upload()

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(CondominiumPhoto.objects.count(), 0)

    def test_envia_foto_para_condominio_da_propria_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self._upload()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.condominium.photos.count(), 1)

    def test_foto_e_salva_na_pasta_da_imobiliaria_com_o_prefixo_do_condominio(self):
        self.client.force_authenticate(self.user)

        self._upload(name="../../invasao.png")

        photo = self.condominium.photos.get()
        self.assertTrue(photo.image.name.startswith(f"photos/{self.agency.slug}/condominium-"))
        # O nome enviado pelo cliente é descartado, então não dá para escapar da pasta.
        self.assertNotIn("invasao", photo.image.name)
        self.assertNotIn("..", photo.image.name)
        self.assertTrue(photo.image.name.endswith(".webp"))

    def test_nao_envia_foto_para_condominio_de_outra_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/condominium-photos/",
            {"condominium": str(self.other_condominium.id), "image": build_image_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CondominiumPhoto.objects.count(), 0)

    def test_listagem_retorna_apenas_fotos_da_propria_imobiliaria(self):
        CondominiumPhoto.objects.create(
            condominium=self.condominium, image=build_image_file()
        )
        alheia = CondominiumPhoto.objects.create(
            condominium=self.other_condominium, image=build_image_file()
        )
        self.client.force_authenticate(self.user)

        response = self.client.get("/condominium-photos/")

        ids = [item["id"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(str(alheia.id), ids)
        self.assertEqual(len(ids), 1)

    def test_primeira_foto_vira_miniatura_e_gera_o_arquivo_mini(self):
        self.client.force_authenticate(self.user)

        self._upload()

        photo = self.condominium.photos.get()
        self.assertTrue(photo.is_main)
        self.assertTrue(photo.image.storage.exists(thumbnail_name(photo.image.name)))

    def test_excluir_foto_apaga_o_arquivo_da_pasta(self):
        self.client.force_authenticate(self.user)
        self._upload()

        photo = self.condominium.photos.get()
        storage = photo.image.storage
        arquivo = photo.image.name

        response = self.client.delete(f"/condominium-photos/{photo.id}/")

        photo.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIsNotNone(photo.deleted_at)
        self.assertFalse(storage.exists(arquivo))
        self.assertFalse(storage.exists(thumbnail_name(arquivo)))

    def test_excluir_a_principal_promove_a_primeira_da_lista(self):
        self.client.force_authenticate(self.user)
        self._upload(name="primeira.png")
        self._upload(name="segunda.png")

        primeira, segunda = list(self.condominium.photos.order_by("position"))
        self.assertTrue(primeira.is_main)

        self.client.delete(f"/condominium-photos/{primeira.id}/")

        segunda.refresh_from_db()
        self.assertTrue(segunda.is_main)

    def test_nao_exclui_foto_de_outra_imobiliaria(self):
        alheia = CondominiumPhoto.objects.create(
            condominium=self.other_condominium, image=build_image_file()
        )
        self.client.force_authenticate(self.user)

        response = self.client.delete(f"/condominium-photos/{alheia.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(CondominiumPhoto.objects.filter(id=alheia.id).exists())

    def test_remove_todas_as_fotos_do_condominio(self):
        self.client.force_authenticate(self.user)
        self._upload(name="a.png")
        self._upload(name="b.png")

        response = self.client.post(
            "/condominium-photos/delete-all/",
            {"condominium": str(self.condominium.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["deleted"], 2)
        self.assertEqual(self.condominium.photos.filter(deleted_at__isnull=True).count(), 0)

    def test_nao_remove_todas_as_fotos_de_condominio_de_outra_imobiliaria(self):
        alheia = CondominiumPhoto.objects.create(
            condominium=self.other_condominium, image=build_image_file()
        )
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/condominium-photos/delete-all/",
            {"condominium": str(self.other_condominium.id)},
            format="json",
        )

        alheia.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNone(alheia.deleted_at)

    def test_reordena_fotos_do_condominio(self):
        self.client.force_authenticate(self.user)
        self._upload(name="a.png")
        self._upload(name="b.png")

        primeira, segunda = list(self.condominium.photos.order_by("position"))

        response = self.client.post(
            "/condominium-photos/reorder/",
            {"photos": [str(segunda.id), str(primeira.id)]},
            format="json",
        )

        primeira.refresh_from_db()
        segunda.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(segunda.position, 1)
        self.assertEqual(primeira.position, 2)

    def test_nao_reordena_incluindo_foto_de_outra_imobiliaria(self):
        self.client.force_authenticate(self.user)
        self._upload()

        propria = self.condominium.photos.get()
        alheia = CondominiumPhoto.objects.create(
            condominium=self.other_condominium, image=build_image_file()
        )

        response = self.client.post(
            "/condominium-photos/reorder/",
            {"photos": [str(alheia.id), str(propria.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_define_outra_foto_como_miniatura(self):
        self.client.force_authenticate(self.user)
        self._upload(name="a.png")
        self._upload(name="b.png")

        primeira, segunda = list(self.condominium.photos.order_by("position"))

        response = self.client.patch(
            f"/condominium-photos/{segunda.id}/", {"is_main": True}, format="json"
        )

        primeira.refresh_from_db()
        segunda.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(segunda.is_main)
        self.assertFalse(primeira.is_main)
        self.assertTrue(segunda.image.storage.exists(thumbnail_name(segunda.image.name)))

    @override_settings(PROPERTY_PHOTO_MAX_PER_PROPERTY=2)
    def test_recusa_foto_acima_do_limite_do_condominio(self):
        self.client.force_authenticate(self.user)

        self.assertEqual(self._upload().status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._upload().status_code, status.HTTP_201_CREATED)
        response = self._upload()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.condominium.photos.count(), 2)


class PropertyCodeTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

    def test_codigo_e_sequencial_por_imobiliaria(self):
        primeiro = Property.objects.create(agency=self.agency, name="Casa 1")
        segundo = Property.objects.create(agency=self.agency, name="Casa 2")
        de_outra = Property.objects.create(agency=self.other_agency, name="Casa da outra")

        self.assertEqual([primeiro.code, segundo.code], ["1", "2"])
        # A numeração é por imobiliária, então a outra também começa em 1.
        self.assertEqual(de_outra.code, "1")

    def test_codigo_vem_do_payload(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/", {"name": "Casa nova", "code": "A-999"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Property.objects.get(name="Casa nova").code, "A-999")

    def test_codigo_ausente_continua_automatico(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/properties/", {"name": "Casa nova"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Property.objects.get(name="Casa nova").code, "1")

    def test_numeracao_automatica_ignora_codigo_com_letra(self):
        Property.objects.create(agency=self.agency, name="Casa 1", code="LOTE-9")
        Property.objects.create(agency=self.agency, name="Casa 2", code="7")

        terceiro = Property.objects.create(agency=self.agency, name="Casa 3")

        self.assertEqual(terceiro.code, "8")

    def test_codigo_repetido_na_imobiliaria_e_recusado(self):
        Property.objects.create(agency=self.agency, name="Casa 1", code="A50")

        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/", {"name": "Casa nova", "code": "a50"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Property.objects.filter(name="Casa nova").exists())

    def test_codigo_repetido_em_outra_imobiliaria_e_aceito(self):
        Property.objects.create(agency=self.other_agency, name="Casa de outra", code="A50")

        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/", {"name": "Casa nova", "code": "A50"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_nome_ausente_e_montado_com_tipo_e_bairro(self):
        property_type = PropertyType.objects.create(name="Apartamento")
        country = Country.objects.create(name="Brasil", code="BRA")
        state = State.objects.create(country=country, name="Rio de Janeiro", abbreviation="RJ")
        city = City.objects.create(state=state, name="Petrópolis", ibge_code="3303906")
        neighborhood = Neighborhood.objects.create(city=city, name="Centro")

        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/",
            {"type": str(property_type.id), "neighborhood": str(neighborhood.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["name"], "Apartamento em Centro")

    def test_nome_ausente_sem_tipo_usa_o_codigo(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/properties/", {"code": "AP77"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["name"], "Imóvel AP77")

    def test_codigo_sobrevive_a_exclusao_de_outro_imovel(self):
        primeiro = Property.objects.create(agency=self.agency, name="Casa 1")
        Property.objects.create(agency=self.agency, name="Casa 2").delete()
        terceiro = Property.objects.create(agency=self.agency, name="Casa 3")

        # O soft delete não devolve o código para a fila.
        self.assertEqual([primeiro.code, terceiro.code], ["1", "3"])

    def test_filtra_por_lista_de_codigos(self):
        Property.objects.create(agency=self.agency, name="Casa 1")
        Property.objects.create(agency=self.agency, name="Casa 2")
        Property.objects.create(agency=self.agency, name="Casa 3")
        self.client.force_authenticate(self.user)

        response = self.client.get("/properties/?code=1,3")

        names = {item["name"] for item in response.data["data"]["results"]}
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(names, {"Casa 1", "Casa 3"})


class AgencySlugTests(APITestCase):
    def test_slug_e_gerado_a_partir_do_nome(self):
        agency = Agency.objects.create(name="Rodrigo Teste")

        self.assertEqual(agency.slug, "rodrigo-teste")

    def test_slug_informado_e_preservado(self):
        agency = Agency.objects.create(name="Imobiliária Central", slug="central")

        self.assertEqual(agency.slug, "central")


class PropertyFilterTests(MediaTestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        country = Country.objects.create(name="Brasil", code="BRA")
        state = State.objects.create(country=country, name="Rio de Janeiro", abbreviation="RJ")
        petropolis = City.objects.create(state=state, name="Petrópolis", ibge_code="3303906")
        rio = City.objects.create(state=state, name="Rio de Janeiro", ibge_code="3304557")

        self.centro = Neighborhood.objects.create(city=petropolis, name="Centro")
        self.itaipava = Neighborhood.objects.create(city=petropolis, name="Itaipava")
        self.copacabana = Neighborhood.objects.create(city=rio, name="Copacabana")
        self.state = state
        self.petropolis = petropolis
        self.rio = rio

        # Local sem nenhum imóvel: não pode aparecer nos selects encadeados.
        self.empty_state = State.objects.create(country=country, name="São Paulo", abbreviation="SP")
        self.empty_city = City.objects.create(state=state, name="Búzios", ibge_code="3300100")
        self.empty_neighborhood = Neighborhood.objects.create(city=petropolis, name="Bingen")

        # Local onde só a outra imobiliária tem imóvel.
        niteroi = City.objects.create(state=state, name="Niterói", ibge_code="3303302")
        self.icarai = Neighborhood.objects.create(city=niteroi, name="Icaraí")
        self.niteroi = niteroi

        self.house = PropertyType.objects.create(name="Casa")
        self.apartment = PropertyType.objects.create(name="Apartamento")
        self.condominium = Condominium.objects.create(agency=self.agency, name="Vila Domênico")

        # Casa no Centro: venda de 500 mil, destaque, fora de condomínio e com foto.
        self.centro_house = Property.objects.create(
            agency=self.agency, type=self.house, neighborhood=self.centro,
            name="Casa no Centro", bedrooms=3, featured=True,
        )
        PropertyPrice.objects.create(
            property=self.centro_house, purpose=PropertyPrice.Purpose.SALE, amount=500000
        )
        PropertyPhoto.objects.create(property=self.centro_house, image=build_image_file())

        # Apartamento em Itaipava: locação barata, dentro de condomínio e inativo.
        self.itaipava_flat = Property.objects.create(
            agency=self.agency, type=self.apartment, neighborhood=self.itaipava,
            condominium=self.condominium, name="Apartamento em Itaipava", bedrooms=2, is_active=False,
        )
        PropertyPrice.objects.create(
            property=self.itaipava_flat, purpose=PropertyPrice.Purpose.RENT, amount=3000
        )

        # Casa em Copacabana: venda cara e locação cara ao mesmo tempo.
        self.rio_house = Property.objects.create(
            agency=self.agency, type=self.house, neighborhood=self.copacabana,
            name="Casa em Copacabana", bedrooms=4, accepts_trade=True, exclusive=True,
        )
        PropertyPrice.objects.create(
            property=self.rio_house, purpose=PropertyPrice.Purpose.SALE, amount=2000000
        )
        PropertyPrice.objects.create(
            property=self.rio_house, purpose=PropertyPrice.Purpose.RENT, amount=8000
        )
        PropertyFee.objects.create(
            property=self.rio_house,
            fee=Fee.objects.get_or_create(name="IPTU")[0],
            amount=900,
        )

        self.other_property = Property.objects.create(
            agency=self.other_agency, type=self.house, neighborhood=self.centro,
            name="Casa de outra imobiliária", bedrooms=4, featured=True,
        )
        PropertyPrice.objects.create(
            property=self.other_property, purpose=PropertyPrice.Purpose.SALE, amount=500000
        )
        Property.objects.create(
            agency=self.other_agency, type=self.house, neighborhood=self.icarai,
            name="Casa em Icaraí", bedrooms=3,
        )

        self.client.force_authenticate(self.user)

    def _names(self, query):
        response = self.client.get(f"/properties/{query}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        return {item["name"] for item in response.data["data"]["results"]}

    def test_filtra_por_finalidade(self):
        self.assertEqual(
            self._names("?purpose=SALE"), {"Casa no Centro", "Casa em Copacabana"}
        )
        self.assertEqual(
            self._names("?purpose=RENT"), {"Apartamento em Itaipava", "Casa em Copacabana"}
        )

    def test_faixa_de_valor_casa_com_a_mesma_finalidade(self):
        # A casa de Copacabana tem locação de 8 mil, mas a venda dela está fora da faixa.
        self.assertEqual(self._names("?purpose=SALE&price_max=10000"), set())
        self.assertEqual(self._names("?purpose=SALE&price_max=600000"), {"Casa no Centro"})

    def test_filtra_por_faixa_de_valor_sem_finalidade(self):
        self.assertEqual(
            self._names("?price_min=400000&price_max=600000"), {"Casa no Centro"}
        )

    def test_filtra_por_numero_minimo_de_dormitorios(self):
        self.assertEqual(
            self._names("?bedrooms_min=3"), {"Casa no Centro", "Casa em Copacabana"}
        )

    def test_filtra_por_cidade_tipo_e_bairro(self):
        self.assertEqual(self._names(f"?city={self.rio.id}"), {"Casa em Copacabana"})
        self.assertEqual(
            self._names(f"?type={self.apartment.id}"), {"Apartamento em Itaipava"}
        )
        self.assertEqual(self._names(f"?neighborhood={self.centro.id}"), {"Casa no Centro"})

    def test_filtra_por_condominio(self):
        self.assertEqual(
            self._names("?has_condominium=true"), {"Apartamento em Itaipava"}
        )
        self.assertEqual(
            self._names("?has_condominium=false"), {"Casa no Centro", "Casa em Copacabana"}
        )
        self.assertEqual(
            self._names(f"?condominium={self.condominium.id}"), {"Apartamento em Itaipava"}
        )

    def test_filtra_por_fotos(self):
        self.assertEqual(self._names("?has_photos=true"), {"Casa no Centro"})
        self.assertEqual(
            self._names("?has_photos=false"),
            {"Apartamento em Itaipava", "Casa em Copacabana"},
        )

    def test_filtra_por_flags_e_situacao(self):
        self.assertEqual(self._names("?featured=true"), {"Casa no Centro"})
        self.assertEqual(self._names("?exclusive=true"), {"Casa em Copacabana"})
        self.assertEqual(self._names("?accepts_trade=true"), {"Casa em Copacabana"})
        self.assertEqual(self._names("?is_active=false"), {"Apartamento em Itaipava"})

    def test_filtra_por_data_de_cadastro(self):
        self.assertEqual(self._names("?created_before=2020-01-01"), set())
        self.assertEqual(len(self._names("?created_before=2100-01-01")), 3)

    def test_pesquisa_livre(self):
        self.assertEqual(self._names("?search=Copacabana"), {"Casa em Copacabana"})

    def test_filtro_nao_vaza_imovel_de_outra_imobiliaria(self):
        # O imóvel da outra imobiliária casa com todos esses filtros.
        self.assertNotIn(
            "Casa de outra imobiliária",
            self._names("?featured=true&purpose=SALE&price_max=600000&bedrooms_min=3"),
        )

    def test_filtra_imoveis_por_estado(self):
        self.assertEqual(len(self._names(f"?state={self.state.id}")), 3)
        self.assertEqual(self._names(f"?state={self.empty_state.id}"), set())

    def test_selects_encadeados_listam_so_locais_com_imovel(self):
        estados = self.client.get("/states/?has_properties=true").data["data"]["results"]
        self.assertEqual([item["abbreviation"] for item in estados], ["RJ"])

        cidades = self.client.get(
            f"/cities/?has_properties=true&state={self.state.id}"
        ).data["data"]["results"]
        self.assertEqual(
            {item["name"] for item in cidades}, {"Petrópolis", "Rio de Janeiro"}
        )

        bairros = self.client.get(
            f"/neighborhoods/?has_properties=true&city={self.petropolis.id}"
        ).data["data"]["results"]
        self.assertEqual({item["name"] for item in bairros}, {"Centro", "Itaipava"})

    def test_local_de_outra_imobiliaria_nao_aparece_nos_selects(self):
        cidades = self.client.get(
            f"/cities/?has_properties=true&state={self.state.id}"
        ).data["data"]["results"]
        self.assertNotIn("Niterói", {item["name"] for item in cidades})

        bairros = self.client.get(
            f"/neighborhoods/?has_properties=true&city={self.niteroi.id}"
        ).data["data"]

        self.assertEqual(bairros["count"], 0)

    def test_ordenacao_por_campo_permitido(self):
        response = self.client.get("/properties/?ordering=name")

        names = [item["name"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(names, sorted(names))


class GlobalCatalogTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        self.other_user = create_user(email="outro@teste.com", password="senha123")
        self.other_user.agency = self.other_agency
        self.other_user.save()

        self.admin = create_user(email="admin@teste.com", password="senha123")
        self.admin.type = "ADMIN"
        self.admin.save()

        self.property_type = PropertyType.objects.create(name="Casa")

    def test_tipo_de_imovel_e_visivel_para_todas_as_imobiliarias(self):
        for user in (self.user, self.other_user):
            self.client.force_authenticate(user)

            response = self.client.get("/property-types/")

            names = [item["name"] for item in response.data["data"]["results"]]
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(names, ["Casa"])

    def test_usuario_comum_nao_pode_criar_tipo_de_imovel(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/property-types/", {"name": "Apartamento"}, format="json")

        # Catálogo global só ADMIN escreve. 403 e não 401: o usuário está autenticado,
        # apenas não tem o privilégio.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(PropertyType.objects.filter(name="Apartamento").exists())

    def test_usuario_comum_nao_pode_editar_tipo_de_imovel(self):
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            f"/property-types/{self.property_type.id}/", {"name": "Alterado"}, format="json"
        )

        self.property_type.refresh_from_db()
        # Catálogo global só ADMIN escreve. 403 e não 401: o usuário está autenticado,
        # apenas não tem o privilégio.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.property_type.name, "Casa")

    def test_admin_pode_criar_tipo_de_imovel(self):
        self.client.force_authenticate(self.admin)

        response = self.client.post("/property-types/", {"name": "Apartamento"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(PropertyType.objects.filter(name="Apartamento").exists())

    def test_bairros_filtram_por_cidade(self):
        country = Country.objects.create(name="Brasil", code="BRA")
        state = State.objects.create(country=country, name="Rio de Janeiro", abbreviation="RJ")
        rio = City.objects.create(state=state, name="Rio de Janeiro", ibge_code="3304557")
        niteroi = City.objects.create(state=state, name="Niterói", ibge_code="3303302")
        Neighborhood.objects.create(city=rio, name="Copacabana")
        Neighborhood.objects.create(city=niteroi, name="Icaraí")

        self.client.force_authenticate(self.user)

        response = self.client.get(f"/neighborhoods/?city={rio.id}")

        names = [item["name"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(names, ["Copacabana"])

    def test_catalogo_global_exige_autenticacao(self):
        response = self.client.get("/property-types/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class FeatureTypeTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        self.property_feature = Feature.objects.create(name="Armário embutido")
        self.condominium_feature = Feature.objects.create(
            name="Salão de festas", type=Feature.Type.CONDOMINIUM
        )

        self.client.force_authenticate(self.user)

    def test_infraestrutura_nova_e_de_imovel_por_padrao(self):
        self.assertEqual(self.property_feature.type, Feature.Type.PROPERTY)

    def test_o_mesmo_nome_pode_existir_nos_dois_cadastros(self):
        Feature.objects.create(name="Piscina")
        Feature.objects.create(name="Piscina", type=Feature.Type.CONDOMINIUM)

        self.assertEqual(Feature.objects.filter(name="Piscina").count(), 2)

    def test_lista_apenas_a_infraestrutura_do_tipo_pedido(self):
        for feature_type, expected in (
            (Feature.Type.PROPERTY, "Armário embutido"),
            (Feature.Type.CONDOMINIUM, "Salão de festas"),
        ):
            response = self.client.get(f"/features/?type={feature_type}")

            names = [item["name"] for item in response.data["data"]["results"]]
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(names, [expected])

    def test_condominio_guarda_a_infraestrutura_selecionada(self):
        response = self.client.post(
            "/condominiums/",
            {"name": "Condomínio A", "features": [str(self.condominium_feature.id)]},
            format="json",
        )

        condominium = Condominium.objects.get(name="Condomínio A")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(list(condominium.features.all()), [self.condominium_feature])

    def test_condominio_nao_aceita_infraestrutura_de_imovel(self):
        response = self.client.post(
            "/condominiums/",
            {"name": "Condomínio A", "features": [str(self.property_feature.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Condominium.objects.filter(name="Condomínio A").exists())

    def test_imovel_nao_aceita_infraestrutura_de_condominio(self):
        response = self.client.post(
            "/properties/",
            {"features": [str(self.condominium_feature.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Property.objects.count(), 0)

    def test_imovel_aceita_infraestrutura_de_imovel(self):
        response = self.client.post(
            "/properties/",
            {"features": [str(self.property_feature.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(list(Property.objects.get().features.all()), [self.property_feature])


class BrokerOwnerTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        self.broker = Broker.objects.create(agency=self.agency, name="Ana")
        self.other_broker = Broker.objects.create(agency=self.other_agency, name="Bruno")
        self.owner = Owner.objects.create(agency=self.agency, name="Carlos")
        self.other_owner = Owner.objects.create(agency=self.other_agency, name="Daniela")

    def test_listagem_de_captadores_traz_apenas_os_da_propria_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/brokers/")

        names = [item["name"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(names, ["Ana"])

    def test_listagem_de_proprietarios_traz_apenas_os_da_propria_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/owners/")

        names = [item["name"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(names, ["Carlos"])

    def test_captador_criado_recebe_a_imobiliaria_do_usuario(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/brokers/", {"name": "Eduardo"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Broker.objects.get(name="Eduardo").agency, self.agency)

    def test_captador_criado_so_com_o_nome_volta_com_id(self):
        # Cadastro rápido feito na tela do imóvel envia apenas o nome digitado.
        self.client.force_authenticate(self.user)

        response = self.client.post("/brokers/", {"name": "Fernanda"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["name"], "Fernanda")
        self.assertTrue(response.data["data"]["id"])

    def test_captador_com_nome_repetido_na_imobiliaria_e_recusado(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/brokers/", {"name": "ana"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Broker.objects.filter(agency=self.agency).count(), 1)

    def test_proprietario_com_nome_repetido_na_imobiliaria_e_recusado(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/owners/", {"name": "Carlos"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Owner.objects.filter(agency=self.agency).count(), 1)

    def test_nome_repetido_em_outra_imobiliaria_e_aceito(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/brokers/", {"name": "Bruno"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Broker.objects.filter(name="Bruno").count(), 2)

    def test_captador_de_outra_imobiliaria_nao_pode_ser_vinculado_ao_imovel(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/",
            {"name": "Casa X", "broker": str(self.other_broker.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_proprietario_de_outra_imobiliaria_nao_pode_ser_vinculado_ao_imovel(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/",
            {"name": "Casa X", "owner": str(self.other_owner.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_listagem_de_captadores_exige_autenticacao(self):
        response = self.client.get("/brokers/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ClientTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        self.client_record = Client.objects.create(agency=self.agency, name="João Silva")
        self.other_client = Client.objects.create(agency=self.other_agency, name="Maria Santos")

    def test_listagem_traz_apenas_os_clientes_da_propria_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/clients/")

        names = [item["name"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(names, ["João Silva"])

    def test_cliente_criado_recebe_a_imobiliaria_do_usuario(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/clients/", {"name": "Pedro Oliveira"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Client.objects.get(name="Pedro Oliveira").agency, self.agency)

    def test_imobiliaria_enviada_no_payload_e_ignorada(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/clients/",
            {"name": "Pedro Oliveira", "agency": str(self.other_agency.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Client.objects.get(name="Pedro Oliveira").agency, self.agency)

    def test_codigo_e_gerado_quando_nao_informado(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/clients/", {"name": "Pedro Oliveira"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["code"], "2")

    def test_codigo_repetido_na_imobiliaria_e_recusado(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/clients/",
            {"name": "Pedro Oliveira", "code": self.client_record.code},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Client.objects.filter(agency=self.agency).count(), 1)

    def test_nome_repetido_e_aceito(self):
        # Homônimo é comum na base de clientes, diferente de captador e proprietário.
        self.client.force_authenticate(self.user)

        response = self.client.post("/clients/", {"name": "João Silva"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Client.objects.filter(agency=self.agency, name="João Silva").count(), 2)

    def test_filtro_por_tipo(self):
        Client.objects.create(agency=self.agency, name="Ana Costa", type=Client.Type.TENANT)
        self.client.force_authenticate(self.user)

        response = self.client.get("/clients/", {"type": Client.Type.TENANT})

        names = [item["name"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(names, ["Ana Costa"])

    def test_cliente_de_outra_imobiliaria_nao_e_encontrado(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(f"/clients/{self.other_client.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cliente_de_outra_imobiliaria_nao_pode_ser_alterado(self):
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            f"/clients/{self.other_client.id}/", {"name": "Alterado"}, format="json"
        )

        self.other_client.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.other_client.name, "Maria Santos")

    def test_exclusao_e_logica_e_some_da_listagem(self):
        self.client.force_authenticate(self.user)

        response = self.client.delete(f"/clients/{self.client_record.id}/")

        self.client_record.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIsNotNone(self.client_record.deleted_at)
        self.assertEqual(self.client.get("/clients/").data["data"]["count"], 0)

    def test_listagem_de_clientes_exige_autenticacao(self):
        response = self.client.get("/clients/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PropertyExporterTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        # A migration do catálogo já cria os portais padrão no banco de teste.
        self.exporter = Exporter.objects.get(name="ZAP Imóveis")
        self.plan = self.exporter.plans.get(name="Destaque")

        self.other_exporter = Exporter.objects.get(name="OLX")
        self.other_plan = self.other_exporter.plans.get(name="Básico")

        # Exportar exige o portal configurado pela imobiliária com limite no plano.
        agency_exporter = AgencyExporter.objects.create(agency=self.agency, exporter=self.exporter)
        AgencyExporterPlan.objects.create(agency_exporter=agency_exporter, plan=self.plan, limit=10)

        self.feature = Feature.objects.create(name="Piscina")

    def test_imovel_salva_exportadores_e_infraestruturas(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/",
            {
                "name": "Casa completa",
                "features": [str(self.feature.id)],
                "exporters": [
                    {"exporter": str(self.exporter.id), "plan": str(self.plan.id)},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = Property.objects.get(name="Casa completa")
        self.assertEqual(list(created.features.values_list("name", flat=True)), ["Piscina"])
        self.assertEqual(created.exporters.count(), 1)
        self.assertEqual(created.exporters.first().plan, self.plan)

    def test_plano_de_outro_exportador_e_recusado(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/",
            {
                "name": "Casa inválida",
                "exporters": [
                    {"exporter": str(self.exporter.id), "plan": str(self.other_plan.id)},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Property.objects.filter(name="Casa inválida").exists())

    def test_imovel_guarda_os_novos_campos_do_formulario(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/properties/",
            {
                "name": "Casa detalhada",
                "local_contact": "Zelador",
                "contact_phone": "(24) 99999-0000",
                "living_rooms": 2,
                "guests": 6,
                "video_url": "https://www.youtube.com/watch?v=abc",
                "visit_notes": "Agendar com antecedência",
                "document_notes": "Escritura em ordem",
                "reserved": True,
                "on_site": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = Property.objects.get(name="Casa detalhada")
        self.assertEqual(created.living_rooms, 2)
        self.assertEqual(created.guests, 6)
        self.assertTrue(created.reserved)
        self.assertTrue(created.on_site)

    def test_usuario_comum_nao_pode_criar_exportador(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/exporters/", {"name": "Novo portal"}, format="json")

        # Catálogo global só ADMIN escreve. 403 e não 401: o usuário está autenticado,
        # apenas não tem o privilégio.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_listagem_de_exportadores_traz_os_planos(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/exporters/")

        results = response.data["data"]["results"]
        zap = next(item for item in results if item["name"] == "ZAP Imóveis")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [plan["name"] for plan in zap["plans"]],
            ["Básico", "Destaque", "Super Destaque"],
        )


class AddressLookupTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        self.country = Country.objects.create(name="Brasil", code="BRA")
        self.state = State.objects.create(
            country=self.country, name="Rio de Janeiro", abbreviation="RJ"
        )
        self.city = City.objects.create(
            state=self.state, name="Petrópolis", ibge_code="3303906"
        )

        self.payload = {
            "cep": "25680-000",
            "logradouro": "Rua Teresa",
            "complemento": "",
            "bairro": "Alto da Serra",
            "localidade": "Petrópolis",
            "uf": "RJ",
            "estado": "Rio de Janeiro",
            "ibge": "3303906",
        }

    @patch("core.services.address._fetch_viacep")
    def test_cep_cria_bairro_que_ainda_nao_existe(self, fetch):
        fetch.return_value = self.payload

        result = find_or_create_address(zip_code="25680-000")

        neighborhood = Neighborhood.objects.get(city=self.city, name="Alto da Serra")
        self.assertEqual(result["neighborhood"]["id"], neighborhood.id)
        self.assertEqual(result["city"]["id"], self.city.id)
        self.assertEqual(result["address"], "Rua Teresa")

    @patch("core.services.address._fetch_viacep")
    def test_cep_reaproveita_bairro_existente(self, fetch):
        fetch.return_value = self.payload
        existing = Neighborhood.objects.create(city=self.city, name="Alto da Serra")

        result = find_or_create_address(zip_code="25680000")

        self.assertEqual(result["neighborhood"]["id"], existing.id)
        self.assertEqual(Neighborhood.objects.filter(city=self.city).count(), 1)

    @patch("core.services.address._fetch_viacep")
    def test_cep_de_cidade_nova_cria_cidade_e_estado(self, fetch):
        fetch.return_value = {
            "logradouro": "Praça da Sé",
            "complemento": "",
            "bairro": "Sé",
            "localidade": "São Paulo",
            "uf": "SP",
            "estado": "São Paulo",
            "ibge": "3550308",
        }

        result = find_or_create_address(zip_code="01001-000")

        city = City.objects.get(ibge_code="3550308")
        self.assertEqual(result["city"]["id"], city.id)
        self.assertEqual(city.state.abbreviation, "SP")
        self.assertEqual(State.objects.filter(abbreviation="SP").count(), 1)

    def test_cep_com_tamanho_invalido_e_recusado(self):
        with self.assertRaises(AddressLookupError):
            find_or_create_address(zip_code="123")

    @patch("core.services.address._fetch_viacep")
    def test_endpoint_retorna_o_endereco(self, fetch):
        fetch.return_value = self.payload
        self.client.force_authenticate(self.user)

        response = self.client.get("/addresses/lookup/?zip_code=25680-000")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["data"]["city"]["name"], "Petrópolis")

    def test_endpoint_sem_autenticacao_falha(self):
        response = self.client.get("/addresses/lookup/?zip_code=25680-000")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_endpoint_com_cep_invalido_retorna_400(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/addresses/lookup/?zip_code=123")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["status"], "error")
        self.assertEqual(response.data["errors"][0]["field"], "zip_code")


class DashboardTests(APITestCase):
    def setUp(self):
        self.plan = Plan.objects.create(name="250 Imóveis", property_limit=250)
        self.agency = Agency.objects.create(name="Imobiliária A", plan=self.plan)
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        house_type = PropertyType.objects.create(name="Casa")

        self.active_house = Property.objects.create(
            agency=self.agency, name="Casa ativa", type=house_type, on_site=True
        )
        PropertyPrice.objects.create(
            property=self.active_house, purpose=PropertyPrice.Purpose.SALE, amount=500000
        )
        Property.objects.create(agency=self.agency, name="Casa inativa", is_active=False)
        self.other_property = Property.objects.create(
            agency=self.other_agency, name="Casa de outra"
        )

    def test_sem_autenticacao_falha(self):
        response = self.client.get("/dashboard/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_numeros_contam_apenas_a_propria_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/dashboard/")

        data = response.data["data"]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["properties"]["total"], 2)
        self.assertEqual(data["properties"]["active"], 1)
        self.assertEqual(data["properties"]["inactive"], 1)
        self.assertEqual(data["properties"]["without_photo"], 2)
        self.assertEqual(data["properties"]["on_site"], 1)
        self.assertEqual(data["properties"]["off_site"], 1)
        self.assertEqual(len(data["recent"]), 2)

    def test_resumo_traz_plano_tipos_e_finalidades(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/dashboard/")

        data = response.data["data"]
        self.assertEqual(data["plan"]["name"], "250 Imóveis")
        self.assertEqual(data["plan"]["property_limit"], 250)
        self.assertEqual(data["types"], [{"name": "Casa", "count": 1}])
        sale = next(item for item in data["purposes"] if item["purpose"] == "SALE")
        self.assertEqual(sale["count"], 1)

    def test_imovel_excluido_fica_de_fora(self):
        Property.objects.create(agency=self.agency, name="Casa excluída").delete()
        self.client.force_authenticate(self.user)

        response = self.client.get("/dashboard/")

        self.assertEqual(response.data["data"]["properties"]["total"], 2)

    def test_exportadores_contam_so_os_imoveis_da_propria_imobiliaria(self):
        # A migration do catálogo já cria os portais padrão no banco de teste.
        exporter = Exporter.objects.get(name="ZAP Imóveis")
        exporter_plan = exporter.plans.get(name="Básico")
        AgencyExporter.objects.create(agency=self.agency, exporter=exporter)
        PropertyExporter.objects.create(
            property=self.active_house, exporter=exporter, plan=exporter_plan
        )
        PropertyExporter.objects.create(
            property=self.other_property, exporter=exporter, plan=exporter_plan
        )
        self.client.force_authenticate(self.user)

        response = self.client.get("/dashboard/")

        zap = next(
            item for item in response.data["data"]["exporters"] if item["name"] == "ZAP Imóveis"
        )
        basico = next(plan for plan in zap["plans"] if plan["name"] == "Básico")
        self.assertEqual(basico["count"], 1)

    def test_resumo_de_exportadores_traz_limite_do_plano_e_total_do_portal(self):
        exporter = Exporter.objects.get(name="ZAP Imóveis")
        basico_plan = exporter.plans.get(name="Básico")
        config = AgencyExporter.objects.create(agency=self.agency, exporter=exporter)
        AgencyExporterPlan.objects.create(agency_exporter=config, plan=basico_plan, limit=5)
        PropertyExporter.objects.create(
            property=self.active_house, exporter=exporter, plan=basico_plan
        )
        # O limite que outra imobiliária contratou no mesmo plano não pode vazar para este resumo.
        other_config = AgencyExporter.objects.create(agency=self.other_agency, exporter=exporter)
        AgencyExporterPlan.objects.create(agency_exporter=other_config, plan=basico_plan, limit=99)
        self.client.force_authenticate(self.user)

        response = self.client.get("/dashboard/")

        zap = next(
            item for item in response.data["data"]["exporters"] if item["name"] == "ZAP Imóveis"
        )
        self.assertEqual(zap["total"], 1)
        basico = next(plan for plan in zap["plans"] if plan["name"] == "Básico")
        self.assertEqual(basico["count"], 1)
        self.assertEqual(basico["limit"], 5)
        # Plano sem contratação vem com limite zero, e não omitido.
        for plan in zap["plans"]:
            if plan["name"] != "Básico":
                self.assertEqual(plan["limit"], 0)

    def test_exportador_nao_configurado_fica_fora_do_resumo(self):
        exporter = Exporter.objects.get(name="ZAP Imóveis")
        AgencyExporter.objects.create(agency=self.agency, exporter=exporter)
        # O portal da outra imobiliária não pode aparecer no resumo desta.
        AgencyExporter.objects.create(
            agency=self.other_agency, exporter=Exporter.objects.get(name="OLX")
        )
        self.client.force_authenticate(self.user)

        response = self.client.get("/dashboard/")

        names = [item["name"] for item in response.data["data"]["exporters"]]
        self.assertEqual(names, ["ZAP Imóveis"])

    def test_usuario_sem_imobiliaria_recebe_resumo_vazio(self):
        admin = create_user(email="admin@teste.com", password="senha123")
        admin.type = User.Type.ADMIN
        admin.save()
        self.client.force_authenticate(admin)

        response = self.client.get("/dashboard/")

        data = response.data["data"]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(data["plan"])
        self.assertEqual(data["properties"]["total"], 0)


class BlogTests(MediaTestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        self.category = BlogCategory.objects.create(agency=self.agency, name="Mercado")
        self.other_category = BlogCategory.objects.create(
            agency=self.other_agency, name="Mercado"
        )

    def _payload(self, **overrides):
        payload = {
            "category": str(self.category.id),
            "title": "Como valorizar seu imóvel",
            "description": "<p>Texto da matéria.</p>",
        }
        payload.update(overrides)

        return payload

    def test_sem_autenticacao_falha(self):
        response = self.client.get("/blog-posts/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cria_materia_e_gera_o_endereco(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/blog-posts/", self._payload(), format="json")

        post = BlogPost.objects.get(title="Como valorizar seu imóvel")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(post.slug, "como-valorizar-seu-imovel")
        self.assertEqual(post.agency, self.agency)
        # Toda matéria nasce como rascunho, para não publicar sem revisão.
        self.assertEqual(post.status, BlogPost.Status.DRAFT)

    def test_endereco_repetido_e_recusado(self):
        BlogPost.objects.create(
            agency=self.agency, category=self.category, title="Como valorizar seu imóvel"
        )
        self.client.force_authenticate(self.user)

        response = self.client.post("/blog-posts/", self._payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(BlogPost.objects.count(), 1)

    def test_mesmo_endereco_em_outra_imobiliaria_e_aceito(self):
        BlogPost.objects.create(
            agency=self.other_agency,
            category=self.other_category,
            title="Como valorizar seu imóvel",
        )
        self.client.force_authenticate(self.user)

        response = self.client.post("/blog-posts/", self._payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(BlogPost.objects.count(), 2)

    def test_categoria_de_outra_imobiliaria_e_recusada(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/blog-posts/", self._payload(category=str(self.other_category.id)), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(BlogPost.objects.exists())

    def test_imobiliaria_enviada_no_payload_e_ignorada(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/blog-posts/", self._payload(agency=str(self.other_agency.id)), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(BlogPost.objects.get().agency, self.agency)

    def test_listagem_traz_apenas_a_propria_imobiliaria(self):
        BlogPost.objects.create(agency=self.agency, category=self.category, title="Minha")
        BlogPost.objects.create(
            agency=self.other_agency, category=self.other_category, title="Da outra"
        )
        self.client.force_authenticate(self.user)

        response = self.client.get("/blog-posts/")

        results = response.data["data"]["results"]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["title"] for item in results], ["Minha"])

    def test_materia_de_outra_imobiliaria_nao_e_encontrada(self):
        post = BlogPost.objects.create(
            agency=self.other_agency, category=self.other_category, title="Da outra"
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(f"/blog-posts/{post.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_filtra_por_situacao(self):
        BlogPost.objects.create(
            agency=self.agency,
            category=self.category,
            title="Publicada",
            status=BlogPost.Status.PUBLISHED,
        )
        BlogPost.objects.create(agency=self.agency, category=self.category, title="Rascunho")
        self.client.force_authenticate(self.user)

        response = self.client.get(f"/blog-posts/?status={BlogPost.Status.PUBLISHED}")

        results = response.data["data"]["results"]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["title"] for item in results], ["Publicada"])

    def test_imagem_e_reduzida_pelo_maior_lado(self):
        self.client.force_authenticate(self.user)

        with override_settings(SITE_IMAGE_MAX_SIDE=800):
            response = self.client.post(
                "/blog-posts/",
                self._payload(image=build_image_file(size=(2400, 1200))),
                format="multipart",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        with Image.open(BlogPost.objects.get().image) as saved:
            self.assertEqual(saved.size, (800, 400))

    def test_tags_chegam_como_texto_json_no_multipart(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/blog-posts/",
            self._payload(tags=json.dumps(["mercado", "dicas"])),
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(BlogPost.objects.get().tags, ["mercado", "dicas"])

    def test_lista_de_tags_vazia_limpa_as_tags(self):
        post = BlogPost.objects.create(
            agency=self.agency,
            category=self.category,
            title="Minha",
            tags=["antiga"],
        )
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            f"/blog-posts/{post.id}/", {"tags": "[]"}, format="multipart"
        )

        post.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(post.tags, [])

    def test_exclusao_e_logica_e_some_da_listagem(self):
        post = BlogPost.objects.create(
            agency=self.agency, category=self.category, title="Minha"
        )
        self.client.force_authenticate(self.user)

        response = self.client.delete(f"/blog-posts/{post.id}/")

        post.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIsNotNone(post.deleted_at)
        self.assertEqual(self.client.get("/blog-posts/").data["data"]["count"], 0)

    def test_categoria_criada_recebe_a_imobiliaria_do_usuario(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/blog-categories/", {"name": "Dicas"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(BlogCategory.objects.get(name="Dicas").agency, self.agency)

    def test_listagem_de_categorias_traz_apenas_a_propria_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/blog-categories/")

        results = response.data["data"]["results"]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in results], [str(self.category.id)])


class AgencyExporterTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        # Portal fora do catálogo padrão: as asserções comparam a lista exata de planos.
        self.exporter = Exporter.objects.create(name="Portal Teste")
        self.gold = ExporterPlan.objects.create(exporter=self.exporter, name="Gold", position=1)
        self.silver = ExporterPlan.objects.create(exporter=self.exporter, name="Prata", position=2)

        self.other_exporter = Exporter.objects.create(name="Portal Teste B")
        self.other_plan = ExporterPlan.objects.create(exporter=self.other_exporter, name="Básico")

    def test_sem_autenticacao_falha(self):
        response = self.client.get("/agency-exporters/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_configura_portal_com_limites_por_plano(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/agency-exporters/",
            {
                "exporter": str(self.exporter.id),
                "plans": [
                    {"plan": str(self.gold.id), "limit": 10},
                    {"plan": str(self.silver.id), "limit": 3},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        config = AgencyExporter.objects.get(agency=self.agency, exporter=self.exporter)
        self.assertEqual(
            {(item.plan_id, item.limit) for item in config.plans.all()},
            {(self.gold.id, 10), (self.silver.id, 3)},
        )

    def test_plano_de_outro_portal_e_recusado(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/agency-exporters/",
            {
                "exporter": str(self.exporter.id),
                "plans": [{"plan": str(self.other_plan.id), "limit": 5}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(AgencyExporter.objects.exists())

    def test_portal_repetido_e_recusado(self):
        AgencyExporter.objects.create(agency=self.agency, exporter=self.exporter)
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/agency-exporters/", {"exporter": str(self.exporter.id)}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(AgencyExporter.objects.count(), 1)

    def test_listagem_traz_apenas_a_propria_imobiliaria(self):
        AgencyExporter.objects.create(agency=self.agency, exporter=self.exporter)
        AgencyExporter.objects.create(agency=self.other_agency, exporter=self.exporter)
        self.client.force_authenticate(self.user)

        response = self.client.get("/agency-exporters/")

        results = response.data["data"]["results"]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(results), 1)

    def test_nao_acessa_configuracao_de_outra_imobiliaria(self):
        other_config = AgencyExporter.objects.create(
            agency=self.other_agency, exporter=self.exporter
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(f"/agency-exporters/{other_config.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_ativacao_espelha_todos_os_planos_do_portal(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/agency-exporters/",
            {
                "exporter": str(self.exporter.id),
                "plans": [{"plan": str(self.gold.id), "limit": 10}],
            },
            format="json",
        )

        config = AgencyExporter.objects.get(agency=self.agency, exporter=self.exporter)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(config.plans.get(plan=self.gold).limit, 10)
        # Plano não informado entra com limite zero, então nenhum imóvel pode usá-lo.
        self.assertEqual(config.plans.get(plan=self.silver).limit, 0)

    def test_atualiza_limites_dos_planos(self):
        config = AgencyExporter.objects.create(agency=self.agency, exporter=self.exporter)
        AgencyExporterPlan.objects.create(agency_exporter=config, plan=self.gold, limit=1)
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            f"/agency-exporters/{config.id}/",
            {"plans": [{"plan": str(self.gold.id), "limit": 10}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(config.plans.get(plan=self.gold).limit, 10)
        self.assertEqual(config.plans.get(plan=self.silver).limit, 0)

    def test_listagem_traz_a_contagem_de_imoveis_exportados(self):
        config = AgencyExporter.objects.create(agency=self.agency, exporter=self.exporter)
        AgencyExporterPlan.objects.create(agency_exporter=config, plan=self.gold, limit=10)
        AgencyExporterPlan.objects.create(agency_exporter=config, plan=self.silver, limit=5)

        for name in ("Casa 1", "Casa 2"):
            imovel = Property.objects.create(agency=self.agency, name=name)
            PropertyExporter.objects.create(
                property=imovel, exporter=self.exporter, plan=self.gold
            )

        self.client.force_authenticate(self.user)

        response = self.client.get("/agency-exporters/")

        portal = response.data["data"]["results"][0]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(portal["exported"], 2)
        self.assertEqual(
            {plan["plan_name"]: (plan["used"], plan["limit"]) for plan in portal["plans"]},
            {"Gold": (2, 10), "Prata": (0, 5)},
        )

    def test_contagem_ignora_imovel_excluido_e_de_outra_imobiliaria(self):
        config = AgencyExporter.objects.create(agency=self.agency, exporter=self.exporter)
        AgencyExporterPlan.objects.create(agency_exporter=config, plan=self.gold, limit=10)

        excluido = Property.objects.create(agency=self.agency, name="Casa excluída")
        PropertyExporter.objects.create(
            property=excluido, exporter=self.exporter, plan=self.gold
        )
        excluido.delete()

        de_outra = Property.objects.create(agency=self.other_agency, name="Casa de outra")
        PropertyExporter.objects.create(
            property=de_outra, exporter=self.exporter, plan=self.gold
        )

        self.client.force_authenticate(self.user)

        response = self.client.get("/agency-exporters/")

        portal = response.data["data"]["results"][0]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(portal["exported"], 0)
        self.assertEqual(portal["plans"][0]["used"], 0)

    def test_excluir_remove_a_configuracao(self):
        config = AgencyExporter.objects.create(agency=self.agency, exporter=self.exporter)
        AgencyExporterPlan.objects.create(agency_exporter=config, plan=self.gold, limit=1)
        self.client.force_authenticate(self.user)

        response = self.client.delete(f"/agency-exporters/{config.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(AgencyExporter.objects.exists())
        self.assertFalse(AgencyExporterPlan.objects.exists())


class PropertyExportLimitTests(APITestCase):
    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        # A migration do catálogo já cria os portais padrão no banco de teste.
        self.exporter = Exporter.objects.get(name="Viva Real")
        self.gold = ExporterPlan.objects.create(exporter=self.exporter, name="Gold")

        self.config = AgencyExporter.objects.create(agency=self.agency, exporter=self.exporter)
        AgencyExporterPlan.objects.create(agency_exporter=self.config, plan=self.gold, limit=1)

        self.client.force_authenticate(self.user)

    def _export_payload(self, name):
        return {
            "name": name,
            "exporters": [{"exporter": str(self.exporter.id), "plan": str(self.gold.id)}],
        }

    def test_exportacao_sem_portal_configurado_e_recusada(self):
        unconfigured = Exporter.objects.get(name="ZAP Imóveis")
        plan = unconfigured.plans.get(name="Básico")

        response = self.client.post(
            "/properties/",
            {
                "name": "Casa X",
                "exporters": [{"exporter": str(unconfigured.id), "plan": str(plan.id)}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Property.objects.exists())

    def test_exportacao_com_limite_zero_e_recusada(self):
        silver = ExporterPlan.objects.create(exporter=self.exporter, name="Prata")
        AgencyExporterPlan.objects.create(agency_exporter=self.config, plan=silver, limit=0)

        response = self.client.post(
            "/properties/",
            {
                "name": "Casa X",
                "exporters": [{"exporter": str(self.exporter.id), "plan": str(silver.id)}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Property.objects.exists())

    def test_limite_do_plano_e_respeitado(self):
        first = self.client.post("/properties/", self._export_payload("Casa 1"), format="json")
        second = self.client.post("/properties/", self._export_payload("Casa 2"), format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Property.objects.filter(name="Casa 2").exists())

    def test_edicao_do_imovel_nao_conta_o_proprio_limite(self):
        created = self.client.post("/properties/", self._export_payload("Casa 1"), format="json")
        property_id = created.data["data"]["id"]

        response = self.client.patch(
            f"/properties/{property_id}/", self._export_payload("Casa 1 editada"), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(PropertyExporter.objects.count(), 1)

    def test_imovel_excluido_libera_a_vaga_do_plano(self):
        self.client.post("/properties/", self._export_payload("Casa 1"), format="json")
        Property.objects.get(name="Casa 1").delete()

        response = self.client.post("/properties/", self._export_payload("Casa 2"), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class SiteContentTests(MediaTestCase):
    """Seções da empresa e banners do site: os dois guardam uma imagem por registro."""

    def setUp(self):
        self.agency = Agency.objects.create(name="Imobiliária A")
        self.other_agency = Agency.objects.create(name="Imobiliária B")

        self.user = create_user(email="user@teste.com", password="senha123")
        self.user.agency = self.agency
        self.user.save()

        self.section = CompanySection.objects.create(agency=self.agency, title="Nossa História")
        self.other_section = CompanySection.objects.create(
            agency=self.other_agency, title="História Alheia"
        )
        self.banner = SiteBanner.objects.create(
            agency=self.agency, title="Banner Principal", image=build_image_file()
        )
        self.other_banner = SiteBanner.objects.create(
            agency=self.other_agency, title="Banner Alheio", image=build_image_file()
        )

    def test_listagem_de_secoes_traz_apenas_as_da_propria_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/company-sections/")

        titles = [item["title"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(titles, ["Nossa História"])

    def test_listagem_de_banners_traz_apenas_os_da_propria_imobiliaria(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/site-banners/")

        titles = [item["title"] for item in response.data["data"]["results"]]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(titles, ["Banner Principal"])

    def test_secao_criada_recebe_a_imobiliaria_do_usuario(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/company-sections/",
            {"title": "Missão", "text": "Nossos princípios", "image": build_image_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(CompanySection.objects.get(title="Missão").agency, self.agency)

    def test_imobiliaria_enviada_no_payload_e_ignorada(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/company-sections/",
            {"title": "Missão", "agency": str(self.other_agency.id)},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(CompanySection.objects.get(title="Missão").agency, self.agency)

    def test_secao_sem_imagem_e_aceita(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/company-sections/", {"title": "Equipe"}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(CompanySection.objects.get(title="Equipe").image)

    def test_banner_sem_imagem_e_recusado(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/site-banners/", {"title": "Sem arte"}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_titulo_em_branco_e_recusado(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/company-sections/", {"title": "   "}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_banner_guarda_link_e_situacao(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/site-banners/",
            {
                "title": "Promoção",
                "link": "https://exemplo.com.br/promocao",
                "is_active": False,
                "image": build_image_file(),
            },
            format="multipart",
        )

        banner = SiteBanner.objects.get(title="Promoção")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(banner.link, "https://exemplo.com.br/promocao")
        self.assertFalse(banner.is_active)

    def test_imagem_do_banner_e_reduzida_pelo_maior_lado(self):
        self.client.force_authenticate(self.user)

        with override_settings(SITE_IMAGE_MAX_SIDE=800):
            self.client.post(
                "/site-banners/",
                {"title": "Grande", "image": build_image_file(size=(2400, 1200))},
                format="multipart",
            )

        with Image.open(SiteBanner.objects.get(title="Grande").image) as saved:
            self.assertEqual(saved.size, (800, 400))

    @override_settings(PROPERTY_PHOTO_MAX_UPLOAD_MB=0)
    def test_imagem_acima_do_limite_e_recusada(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/site-banners/",
            {"title": "Pesada", "image": build_image_file(size=(50, 50))},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_formato_nao_aceito_e_recusado(self):
        self.client.force_authenticate(self.user)
        arquivo = SimpleUploadedFile("arte.gif", b"nao-e-imagem", content_type="image/gif")

        response = self.client.post(
            "/site-banners/", {"title": "Errada", "image": arquivo}, format="multipart"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_trocar_a_imagem_apaga_a_anterior(self):
        self.client.force_authenticate(self.user)
        anterior = self.banner.image.name

        response = self.client.patch(
            f"/site-banners/{self.banner.id}/",
            {"image": build_image_file(name="nova.png")},
            format="multipart",
        )

        self.banner.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotEqual(self.banner.image.name, anterior)
        self.assertFalse(self.banner.image.storage.exists(anterior))

    def test_editar_o_titulo_mantem_a_imagem(self):
        self.client.force_authenticate(self.user)
        anterior = self.banner.image.name

        response = self.client.patch(
            f"/site-banners/{self.banner.id}/", {"title": "Renomeado"}, format="json"
        )

        self.banner.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.banner.image.name, anterior)
        self.assertTrue(self.banner.image.storage.exists(anterior))

    def test_secao_de_outra_imobiliaria_nao_e_encontrada(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(f"/company-sections/{self.other_section.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_banner_de_outra_imobiliaria_nao_pode_ser_alterado(self):
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            f"/site-banners/{self.other_banner.id}/", {"title": "Invadido"}, format="json"
        )

        self.other_banner.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.other_banner.title, "Banner Alheio")

    def test_exclusao_e_logica_e_some_da_listagem(self):
        self.client.force_authenticate(self.user)

        response = self.client.delete(f"/site-banners/{self.banner.id}/")

        self.banner.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIsNotNone(self.banner.deleted_at)
        self.assertEqual(self.client.get("/site-banners/").data["data"]["count"], 0)

    def test_imagem_fica_na_pasta_da_imobiliaria(self):
        # O caminho isola o arquivo por imobiliária e ignora o nome enviado pelo cliente.
        self.client.force_authenticate(self.user)

        self.client.post(
            "/site-banners/",
            {"title": "Isolado", "image": build_image_file(name="../fuga.png")},
            format="multipart",
        )

        caminho = PurePosixPath(SiteBanner.objects.get(title="Isolado").image.name)
        self.assertEqual(caminho.parent, PurePosixPath(f"site/{self.agency.slug}"))
        self.assertTrue(caminho.name.startswith("sitebanner-"))

    def test_listagem_de_banners_exige_autenticacao(self):
        response = self.client.get("/site-banners/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_listagem_de_secoes_exige_autenticacao(self):
        response = self.client.get("/company-sections/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
