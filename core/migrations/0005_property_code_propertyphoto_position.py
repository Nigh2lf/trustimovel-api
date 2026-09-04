from django.db import migrations, models


def fill_property_codes(apps, schema_editor):
    # Numera os imóveis já cadastrados por imobiliária, na ordem em que foram criados.
    Property = apps.get_model('core', 'Property')
    codes = {}

    for instance in Property.objects.order_by('agency_id', 'created_at').only('id', 'agency_id'):
        next_code = codes.get(instance.agency_id, 0) + 1
        codes[instance.agency_id] = next_code
        Property.objects.filter(pk=instance.pk).update(code=next_code)


def fill_photo_positions(apps, schema_editor):
    PropertyPhoto = apps.get_model('core', 'PropertyPhoto')
    positions = {}

    for photo in PropertyPhoto.objects.order_by('property_id', 'created_at').only('id', 'property_id'):
        next_position = positions.get(photo.property_id, 0) + 1
        positions[photo.property_id] = next_position
        PropertyPhoto.objects.filter(pk=photo.pk).update(position=next_position)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_agency_slug_alter_propertyphoto_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='property',
            name='code',
            field=models.PositiveIntegerField(
                editable=False,
                help_text='Código do imóvel dentro da imobiliária',
                null=True,
            ),
        ),
        migrations.RunPython(fill_property_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='property',
            name='code',
            field=models.PositiveIntegerField(
                editable=False,
                help_text='Código do imóvel dentro da imobiliária',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='property',
            unique_together={('agency', 'code')},
        ),
        migrations.AddField(
            model_name='propertyphoto',
            name='position',
            field=models.PositiveSmallIntegerField(default=0, help_text='Ordem da foto na galeria'),
        ),
        migrations.RunPython(fill_photo_positions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='propertyphoto',
            name='is_main',
            field=models.BooleanField(default=False, help_text='Foto usada como miniatura do imóvel'),
        ),
        migrations.AlterModelOptions(
            name='propertyphoto',
            options={
                'ordering': ('position', 'created_at'),
                'verbose_name': 'Foto do imóvel',
                'verbose_name_plural': 'Fotos do imóvel',
            },
        ),
    ]
