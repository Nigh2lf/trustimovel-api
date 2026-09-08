"""Testes do comando syncmedia.

O cenário é o da migração real: o banco aponta para arquivos que só existem na pasta media local,
e o storage padrão é outro lugar (aqui uma segunda pasta temporária, no lugar do S3). Nenhum
teste fala com a AWS.
"""

import os
import shutil
import tempfile
from io import BytesIO, StringIO

from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from PIL import Image

from core.models import Agency, Property, PropertyPhoto
from core.services.photos import thumbnail_name

SOURCE_ROOT = tempfile.mkdtemp()
DEST_ROOT = tempfile.mkdtemp()


class DestinationStorage(FileSystemStorage):
    """Faz o papel do S3: um storage padrão que não é a pasta media local."""

    def __init__(self, **kwargs):
        kwargs.setdefault('location', DEST_ROOT)
        super().__init__(**kwargs)


DEST_STORAGES = {
    'default': {'BACKEND': 'core.tests_syncmedia.DestinationStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# Storage padrão na própria pasta media: o cenário em que o comando deve se recusar a rodar.
SAME_PLACE_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def image_file(name='foto.png', size=(4, 4)):
    buffer = BytesIO()
    Image.new('RGB', size).save(buffer, format='PNG')

    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=SOURCE_ROOT, STORAGES=DEST_STORAGES)
class MigrateMediaTests(TestCase):
    def setUp(self):
        for root in (SOURCE_ROOT, DEST_ROOT):
            shutil.rmtree(root, ignore_errors=True)
            os.makedirs(root)

        self.agency = Agency.objects.create(name='Imobiliária Um')
        self.property = Property.objects.create(agency=self.agency, name='Casa')

    def create_local_photo(self, *, is_main=False):
        """Foto gravada pelo caminho normal e depois movida para a pasta local, como antes do S3."""
        photo = PropertyPhoto.objects.create(
            property=self.property, image=image_file(), is_main=is_main
        )
        destination = os.path.join(DEST_ROOT, photo.image.name)
        local = os.path.join(SOURCE_ROOT, photo.image.name)
        os.makedirs(os.path.dirname(local), exist_ok=True)
        shutil.move(destination, local)

        return photo

    def run_command(self, *args):
        out = StringIO()
        call_command('syncmedia', *args, stdout=out)

        return out.getvalue()

    def in_dest(self, name):
        return os.path.isfile(os.path.join(DEST_ROOT, name))

    def test_envia_os_arquivos_locais_e_regenera_a_miniatura_da_principal(self):
        main = self.create_local_photo(is_main=True)
        other = self.create_local_photo()
        names_before = {main.image.name, other.image.name}

        output = self.run_command()

        self.assertTrue(self.in_dest(main.image.name))
        self.assertTrue(self.in_dest(other.image.name))
        self.assertTrue(self.in_dest(thumbnail_name(main.image.name)))
        self.assertFalse(self.in_dest(thumbnail_name(other.image.name)))
        # O banco não muda: o caminho relativo é o mesmo, só o storage passa a ter o arquivo.
        self.assertEqual(
            set(PropertyPhoto.objects.values_list('image', flat=True)), names_before
        )
        self.assertIn('Enviados: 2', output)
        self.assertIn('miniaturas regeneradas: 1', output)

    def test_dry_run_nao_grava_nada(self):
        photo = self.create_local_photo(is_main=True)

        output = self.run_command('--dry-run')

        self.assertFalse(self.in_dest(photo.image.name))
        self.assertFalse(self.in_dest(thumbnail_name(photo.image.name)))
        self.assertIn('enviaria:', output)
        self.assertIn('regeneraria a miniatura', output)

    def test_nao_reenvia_o_que_ja_esta_no_storage(self):
        photo = self.create_local_photo()
        destination = os.path.join(DEST_ROOT, photo.image.name)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with open(destination, 'wb') as handle:
            handle.write(b'ja estava aqui')

        output = self.run_command()

        with open(destination, 'rb') as handle:
            self.assertEqual(handle.read(), b'ja estava aqui')
        self.assertIn('já no storage: 1', output)
        self.assertNotIn('renomeados', output)

    def test_arquivo_perdido_e_reportado_sem_interromper(self):
        lost = self.create_local_photo(is_main=True)
        os.remove(os.path.join(SOURCE_ROOT, lost.image.name))
        ok = self.create_local_photo()

        output = self.run_command()

        self.assertTrue(self.in_dest(ok.image.name))
        self.assertIn('sem arquivo local nem no storage', output)
        # Original perdida: a miniatura também não pode ser regenerada.
        self.assertIn('sem arquivo em lugar nenhum: 2', output)

    def test_orfaos_so_vao_com_a_flag(self):
        orphan = os.path.join(SOURCE_ROOT, 'photos', 'solto.png')
        os.makedirs(os.path.dirname(orphan), exist_ok=True)
        with open(orphan, 'wb') as handle:
            handle.write(b'sem registro')

        output = self.run_command()
        self.assertFalse(self.in_dest('photos/solto.png'))
        self.assertIn('sem registro (ignorados', output)

        self.run_command('--orphans')
        self.assertTrue(self.in_dest('photos/solto.png'))

    @override_settings(STORAGES=SAME_PLACE_STORAGES)
    def test_recusa_rodar_com_storage_apontando_para_a_propria_pasta_local(self):
        with self.assertRaises(CommandError):
            call_command('syncmedia', stdout=StringIO())
