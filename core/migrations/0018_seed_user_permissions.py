"""Dá acesso total a todos os recursos para os usuários que já existiam.

Sem isto, o deploy que liga o permissionamento tira o acesso de todo mundo de uma vez:
a permissão falha fechada, e ninguém teria sequer o recurso `usuarios` para se recuperar
sozinho — só o painel da plataforma resolveria, cliente por cliente.

Vale só para quem já estava na base. Usuário novo nasce sem nada e recebe o que o gestor
marcar na tela.
"""

import uuid

from django.db import migrations

from core.resources import RESOURCES, AccessLevel


def grant_full_access(apps, schema_editor):
    User = apps.get_model('core', 'User')
    UserPermission = apps.get_model('core', 'UserPermission')

    existing = {
        (str(user_id), resource)
        for user_id, resource in UserPermission.objects.values_list('user_id', 'resource')
    }

    rows = []

    for user in User.objects.filter(deleted_at__isnull=True).iterator():
        for resource in RESOURCES:
            if (str(user.id), resource.key) in existing:
                continue

            level = AccessLevel.READ if resource.read_only else AccessLevel.FULL

            rows.append(
                UserPermission(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    resource=resource.key,
                    level=level,
                )
            )

    UserPermission.objects.bulk_create(rows, batch_size=500)


def revert(apps, schema_editor):
    # As concessões voltam a não existir; o modelo inteiro sai na migração anterior.
    UserPermission = apps.get_model('core', 'UserPermission')
    UserPermission.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_userpermission'),
    ]

    operations = [
        migrations.RunPython(grant_full_access, revert),
    ]
