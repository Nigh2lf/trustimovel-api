import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import City, Country, Neighborhood, State

STATE_PATTERN = re.compile(r"values \(\d+, '(.+)', '([A-Z]{2})', \d+\);")
CODE_PATTERN = re.compile(r"values \('(\w+)','(.+)',\s*'([A-Z]{2})'\);")


class Command(BaseCommand):
    help = 'Popula Brasil, estados, cidades e bairros a partir de Estados.sql, Municipios.sql e Bairros.sql'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dir',
            dest='directory',
            default=str(Path(settings.BASE_DIR).parent),
            help='Diretório com os arquivos Estados.sql, Municipios.sql e Bairros.sql',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        directory = Path(options['directory'])

        state_rows = self._read(directory / 'Estados.sql', STATE_PATTERN)
        city_rows = self._read(directory / 'Municipios.sql', CODE_PATTERN)
        neighborhood_rows = self._read(directory / 'Bairros.sql', CODE_PATTERN)

        country = self._create_country()
        states = self._create_states(country, state_rows)
        cities = self._create_cities(states, city_rows)
        self._create_neighborhoods(cities, neighborhood_rows)

        self.stdout.write(self.style.SUCCESS('Seed concluído.'))

    def _read(self, path, pattern):
        if not path.exists():
            raise CommandError(f'Arquivo não encontrado: {path}')

        rows = []

        with path.open(encoding='utf-8') as sql_file:
            for line in sql_file:
                match = pattern.search(line)

                if match:
                    # O dump escapa aspas simples duplicando-as.
                    rows.append(tuple(value.replace("''", "'") for value in match.groups()))

        if not rows:
            raise CommandError(f'Nenhum registro reconhecido em {path}')

        return rows

    def _create_country(self):
        country, created = Country.objects.get_or_create(code='BRA', defaults={'name': 'Brasil'})
        self.stdout.write(f'País {country.name}: {"criado" if created else "já existia"}')

        return country

    def _create_states(self, country, rows):
        existing = set(State.objects.filter(country=country).values_list('abbreviation', flat=True))
        new_states = [
            State(country=country, name=name, abbreviation=abbreviation)
            for name, abbreviation in rows
            if abbreviation not in existing
        ]

        State.objects.bulk_create(new_states)
        self.stdout.write(f'Estados: {len(new_states)} criados, {len(existing)} já existiam')

        return {
            state.abbreviation: state
            for state in State.objects.filter(country=country)
        }

    def _create_cities(self, states, rows):
        existing = set(City.objects.values_list('ibge_code', flat=True))
        new_cities = []

        for ibge_code, name, abbreviation in rows:
            state = states.get(abbreviation)

            if state is None or ibge_code in existing:
                continue

            new_cities.append(City(state=state, name=name, ibge_code=ibge_code))

        City.objects.bulk_create(new_cities, batch_size=1000)
        self.stdout.write(f'Cidades: {len(new_cities)} criadas, {len(existing)} já existiam')

        return {
            ibge_code: (city_id, name)
            for ibge_code, city_id, name in City.objects.values_list('ibge_code', 'id', 'name')
        }

    def _create_neighborhoods(self, cities, rows):
        existing = set(Neighborhood.objects.values_list('city_id', 'name'))
        existing_count = len(existing)
        new_neighborhoods = []

        for code, name, abbreviation in rows:
            # Os sete primeiros dígitos do código do bairro são o código IBGE do município.
            city = cities.get(code[:7])

            if city is None:
                continue

            city_id, city_name = city
            suffix = f' - {city_name}'

            if name.endswith(suffix):
                name = name[: -len(suffix)]

            key = (city_id, name)

            if key in existing:
                continue

            existing.add(key)
            new_neighborhoods.append(Neighborhood(city_id=city_id, name=name))

        Neighborhood.objects.bulk_create(new_neighborhoods, batch_size=1000)
        self.stdout.write(f'Bairros: {len(new_neighborhoods)} criados, {existing_count} já existiam')
