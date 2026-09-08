"""Envia para o storage padrão (o S3, quando configurado) os arquivos da pasta `media` local que
o banco referencia. Não altera nenhum registro.

Os campos de arquivo guardam só o caminho relativo (ex.: `photos/<slug>/property-<uuid>.webp`); a
URL é montada pelo storage. Basta o objeto existir no bucket com a mesma chave para a foto abrir
pelo S3 exatamente como se tivesse sido enviada pelo painel.
"""

import os

from django.apps import apps
from django.conf import settings
from django.core.files import File
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from core.models import Photo
from core.services.photos import build_thumbnail, thumbnail_name


class Command(BaseCommand):
    help = 'Envia os arquivos da pasta media local referenciados no banco para o storage padrão (S3).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true', help='Só lista o que seria enviado, sem gravar nada.'
        )
        parser.add_argument(
            '--orphans',
            action='store_true',
            help='Envia também os arquivos locais que nenhum registro referencia.',
        )

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        self.storage = default_storage
        self.media_root = settings.MEDIA_ROOT
        self.stats = {'uploaded': 0, 'skipped': 0, 'missing': 0, 'rebuilt': 0, 'renamed': 0}

        if isinstance(self.storage, FileSystemStorage) and os.path.abspath(
            self.storage.location
        ) == os.path.abspath(self.media_root):
            raise CommandError(
                'O storage padrão é a própria pasta media local. Configure o S3 (AWS_*) antes de rodar.'
            )

        # Lista o bucket uma vez em vez de um HEAD por arquivo; fora do S3 cai no exists().
        self.existing = self._existing_names()
        # O que este comando já gravou (ou gravaria, no --dry-run): a mini depende da original.
        self.known = set()
        referenced = set()

        if self.dry_run:
            self.stdout.write(self.style.WARNING('Simulação: nada será enviado.'))

        for model, field in self._file_fields():
            rows = model._default_manager.exclude(**{field.name: ''}).exclude(
                **{f'{field.name}__isnull': True}
            )
            self.stdout.write(f'{model.__name__}.{field.name}: {rows.count()} registro(s)')

            for instance in rows.iterator():
                name = getattr(instance, field.name).name
                referenced.add(name)
                self._ensure(name)

                # A mini existe só para a foto principal; sem ela o card do imóvel fica sem imagem.
                if isinstance(instance, Photo) and instance.is_main:
                    mini = thumbnail_name(name)
                    referenced.add(mini)
                    self._ensure(mini, rebuild_from=instance)

        orphans = [name for name in self._local_files() if name not in referenced]

        if options['orphans']:
            self.stdout.write(f'Arquivos locais sem registro: {len(orphans)}')
            for name in orphans:
                self._ensure(name)
        elif orphans:
            self.stdout.write(
                f'Arquivos locais sem registro (ignorados; use --orphans para enviar): {len(orphans)}'
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Enviados: {self.stats['uploaded']} | já no storage: {self.stats['skipped']} | "
                f"miniaturas regeneradas: {self.stats['rebuilt']} | "
                f"sem arquivo em lugar nenhum: {self.stats['missing']}"
                + (f" | renomeados pelo storage: {self.stats['renamed']}" if self.stats['renamed'] else '')
            )
        )

    # ----- passos -----

    def _ensure(self, name, *, rebuild_from=None):
        """Garante `name` no storage: pula se já existe, envia o local, ou regenera a miniatura."""
        if self._exists(name):
            self.stats['skipped'] += 1
            return

        local_path = os.path.join(self.media_root, name)

        if os.path.isfile(local_path):
            self._upload(name, local_path)
            return

        if rebuild_from is not None and self._exists(rebuild_from.image.name):
            self._rebuild_thumbnail(rebuild_from, name)
            return

        self.stats['missing'] += 1
        self.stdout.write(self.style.WARNING(f'  sem arquivo local nem no storage: {name}'))

    def _upload(self, name, local_path):
        self.stats['uploaded'] += 1

        if self.dry_run:
            self.stdout.write(f'  enviaria: {name}')
            self._remember(name)
            return

        with open(local_path, 'rb') as handle:
            saved_name = self.storage.save(name, File(handle, name=name))

        self._remember(saved_name)

        if saved_name != name:
            # Só chegamos aqui porque exists() era falso, então não deveria acontecer.
            self.stats['renamed'] += 1
            self.stdout.write(
                self.style.ERROR(
                    f'  storage gravou {name} como {saved_name}; o registro continua apontando para {name}'
                )
            )
        else:
            self.stdout.write(f'  enviado: {name}')

    def _rebuild_thumbnail(self, photo, name):
        self.stats['rebuilt'] += 1

        if self.dry_run:
            self.stdout.write(f'  regeneraria a miniatura: {name}')
            self._remember(name)
            return

        # build_thumbnail lê a original pelo storage da foto, que é o mesmo storage padrão.
        self._remember(build_thumbnail(photo))
        self.stdout.write(f'  miniatura regenerada: {name}')

    # ----- apoio -----

    def _file_fields(self):
        for model in sorted(apps.get_models(), key=lambda item: item.__name__):
            if model._meta.app_label != 'core':
                continue

            for field in model._meta.get_fields():
                if isinstance(field, models.FileField):
                    yield model, field

    def _local_files(self):
        for root, _dirs, files in os.walk(self.media_root):
            for filename in sorted(files):
                relative = os.path.relpath(os.path.join(root, filename), self.media_root)
                yield relative.replace(os.sep, '/')

    def _existing_names(self):
        bucket = getattr(self.storage, 'bucket', None)

        if bucket is None:
            return None

        location = getattr(self.storage, 'location', '') or ''
        prefix = f'{location.strip("/")}/' if location else ''

        return {obj.key[len(prefix):] for obj in bucket.objects.filter(Prefix=prefix)}

    def _exists(self, name):
        if name in self.known:
            return True

        if self.existing is not None:
            return name in self.existing

        return self.storage.exists(name)

    def _remember(self, name):
        self.known.add(name)
