from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_property_code_propertyphoto_position'),
    ]

    operations = [
        migrations.AddField(
            model_name='propertyphoto',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='propertyphoto',
            name='file_size',
            field=models.PositiveIntegerField(default=0, help_text='Tamanho do arquivo em bytes'),
        ),
    ]
