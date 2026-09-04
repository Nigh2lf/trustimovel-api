from django.db import migrations, models
from django.utils.text import slugify


def fill_slugs(apps, schema_editor):
    Exporter = apps.get_model('core', 'Exporter')
    used = set()

    for exporter in Exporter.objects.order_by('name'):
        base = slugify(exporter.name) or str(exporter.id)
        slug = base
        counter = 2

        # Nomes diferentes podem gerar o mesmo slug, e a coluna vai virar única.
        while slug in used:
            slug = f'{base}-{counter}'
            counter += 1

        used.add(slug)
        exporter.slug = slug
        exporter.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_client'),
    ]

    # A coluna nasce sem unique, os portais existentes recebem o slug e só então ele vira único.
    operations = [
        migrations.AddField(
            model_name='exporter',
            name='slug',
            field=models.SlugField(blank=True, default='', help_text='Identifica o portal na URL de exportação', max_length=120),
            preserve_default=False,
        ),
        migrations.RunPython(fill_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='exporter',
            name='slug',
            field=models.SlugField(blank=True, help_text='Identifica o portal na URL de exportação', max_length=120, unique=True),
        ),
    ]
