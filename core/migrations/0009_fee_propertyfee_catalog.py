import uuid

import django.db.models.deletion
from django.db import migrations, models

# Taxas iniciais do catálogo; as duas primeiras substituem o choices antigo de PropertyFee.
FEES = ['Condomínio', 'IPTU', 'Seguro', 'Taxa de Incêndio']
FEE_BY_TYPE = {'CONDOMINIUM': 'Condomínio', 'PROPERTY_TAX': 'IPTU'}


def create_fees(apps, schema_editor):
    Fee = apps.get_model('core', 'Fee')
    PropertyFee = apps.get_model('core', 'PropertyFee')

    fees = {name: Fee.objects.get_or_create(name=name)[0] for name in FEES}

    for fee_type, name in FEE_BY_TYPE.items():
        PropertyFee.objects.filter(fee_type=fee_type).update(fee=fees[name])


def restore_fee_types(apps, schema_editor):
    PropertyFee = apps.get_model('core', 'PropertyFee')
    type_by_name = {name: fee_type for fee_type, name in FEE_BY_TYPE.items()}

    for name, fee_type in type_by_name.items():
        PropertyFee.objects.filter(fee__name=name).update(fee_type=fee_type)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_property_code_and_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='Fee',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=120, unique=True)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Taxa',
                'verbose_name_plural': 'Taxas',
                'ordering': ('name',),
            },
        ),
        # O unique antigo sai antes para o campo fee_type poder ser removido no fim.
        migrations.AlterUniqueTogether(
            name='propertyfee',
            unique_together=set(),
        ),
        migrations.AddField(
            model_name='propertyfee',
            name='fee',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='property_fees',
                to='core.fee',
            ),
        ),
        migrations.RunPython(create_fees, restore_fee_types),
        migrations.AlterField(
            model_name='propertyfee',
            name='fee',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='property_fees',
                to='core.fee',
            ),
        ),
        migrations.RemoveField(
            model_name='propertyfee',
            name='fee_type',
        ),
        migrations.AlterUniqueTogether(
            name='propertyfee',
            unique_together={('property', 'fee')},
        ),
    ]
