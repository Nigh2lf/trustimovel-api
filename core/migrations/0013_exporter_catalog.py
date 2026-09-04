from django.db import migrations

# Portais do sistema antigo, cada um com os planos na ordem de exibição.
EXPORTERS = [
    ('Petrópolis Imóveis', ['Básico', 'Destaque', 'Super Destaque']),
    ('Teresópolis Imóveis', ['Básico', 'Destaque']),
    ('ZAP Imóveis', ['Básico', 'Destaque', 'Super Destaque']),
    ('Viva Real', ['Básico', 'Destaque', 'Super Destaque']),
    ('OLX', ['Básico']),
    ('Mercado Livre', ['Prata', 'Ouro', 'Diamante']),
    ('Imóvel Web', ['Básico', 'Destaque', 'Super Destaque']),
    ('Zip Anúncios', ['Básico']),
    ('Buskaza', ['Básico', 'Destaque', 'Super Destaque']),
    ('Juiz de Fora Imóveis', ['Básico', 'Destaque']),
    ('Portal 123i', ['Básico']),
]


def seed_exporters(apps, schema_editor):
    Exporter = apps.get_model('core', 'Exporter')
    ExporterPlan = apps.get_model('core', 'ExporterPlan')

    for name, plans in EXPORTERS:
        exporter, _ = Exporter.objects.get_or_create(name=name)

        for position, plan_name in enumerate(plans, start=1):
            ExporterPlan.objects.get_or_create(
                exporter=exporter, name=plan_name, defaults={'position': position}
            )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_agencyexporter_agencyexporterplan'),
    ]

    operations = [
        # Sem reverso: apagar portais poderia levar embora configurações e imóveis exportados.
        migrations.RunPython(seed_exporters, migrations.RunPython.noop),
    ]
