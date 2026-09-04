from django.db import migrations, models
from django.utils.text import slugify

import core.models


def fill_agency_slugs(apps, schema_editor):
    # Preenche as imobiliárias já cadastradas antes do slug virar único.
    Agency = apps.get_model('core', 'Agency')
    used = set()

    for agency in Agency.objects.all():
        base = slugify(agency.name) or str(agency.id)[:8]
        slug = base
        suffix = 2

        while slug in used:
            slug = f'{base}-{suffix}'
            suffix += 1

        used.add(slug)
        agency.slug = slug
        agency.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_alter_propertyfee_fee_type_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='agency',
            name='slug',
            field=models.SlugField(
                blank=True,
                default='',
                help_text='Usado na pasta de arquivos da imobiliária',
                max_length=100,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(fill_agency_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='agency',
            name='slug',
            field=models.SlugField(
                blank=True,
                help_text='Usado na pasta de arquivos da imobiliária',
                max_length=100,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name='propertyphoto',
            name='image',
            field=models.ImageField(upload_to=core.models.property_photo_upload_to),
        ),
    ]
