from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django_filters import rest_framework as filters

from core.models import (
    City,
    Condominium,
    Deal,
    Neighborhood,
    Property,
    PropertyPhoto,
    PropertyPrice,
    PropertyType,
    State,
    Task,
)


class LocationFilterSet(filters.FilterSet):
    """Base dos catálogos de local, com a opção de listar só onde a imobiliária tem imóvel."""

    has_properties = filters.BooleanFilter(method='filter_has_properties')

    # Caminho de Property até o model filtrado, definido em cada catálogo.
    property_lookup = None

    def filter_has_properties(self, queryset, name, value):
        user = getattr(self.request, 'user', None)
        properties = Property.objects.filter(
            agency_id=getattr(user, 'agency_id', None),
            deleted_at__isnull=True,
            **{self.property_lookup: OuterRef('pk')},
        )

        return queryset.filter(Exists(properties)) if value else queryset.filter(~Exists(properties))


class StateFilter(LocationFilterSet):
    property_lookup = 'neighborhood__city__state'

    class Meta:
        model = State
        fields = ['country']


class CityFilter(LocationFilterSet):
    property_lookup = 'neighborhood__city'

    class Meta:
        model = City
        fields = ['state']


class NeighborhoodFilter(LocationFilterSet):
    property_lookup = 'neighborhood'

    class Meta:
        model = Neighborhood
        fields = ['city']


class CharInFilter(filters.BaseInFilter, filters.CharFilter):
    """Aceita uma lista separada por vírgula, ex.: code=125,A35,182."""


class PropertyFilter(filters.FilterSet):
    """Filtros avançados da listagem de imóveis."""

    code = CharInFilter(field_name='code', lookup_expr='in')
    purpose = filters.ChoiceFilter(choices=PropertyPrice.Purpose.choices, method='filter_by_price')
    price_min = filters.NumberFilter(method='filter_by_price')
    price_max = filters.NumberFilter(method='filter_by_price')

    bedrooms_min = filters.NumberFilter(field_name='bedrooms', lookup_expr='gte')
    created_before = filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    type = filters.ModelChoiceFilter(queryset=PropertyType.objects.all())
    condominium = filters.ModelChoiceFilter(queryset=Condominium.objects.all())
    neighborhood = filters.ModelChoiceFilter(queryset=Neighborhood.objects.all())
    city = filters.ModelChoiceFilter(field_name='neighborhood__city', queryset=City.objects.all())
    state = filters.ModelChoiceFilter(
        field_name='neighborhood__city__state', queryset=State.objects.all()
    )

    has_condominium = filters.BooleanFilter(method='filter_has_condominium')
    has_photos = filters.BooleanFilter(method='filter_has_photos')

    class Meta:
        model = Property
        fields = ['is_active', 'featured', 'exclusive', 'accepts_trade']

    def filter_by_price(self, queryset, name, value):
        # Finalidade e faixa de valor precisam casar na mesma linha de preço, então são aplicadas juntas.
        if getattr(self, '_price_filtered', False):
            return queryset

        self._price_filtered = True
        data = self.form.cleaned_data
        prices = PropertyPrice.objects.filter(property=OuterRef('pk'))

        if data.get('purpose'):
            prices = prices.filter(purpose=data['purpose'])

        if data.get('price_min') is not None:
            prices = prices.filter(amount__gte=data['price_min'])

        if data.get('price_max') is not None:
            prices = prices.filter(amount__lte=data['price_max'])

        return queryset.filter(Exists(prices))

    def filter_has_condominium(self, queryset, name, value):
        return queryset.filter(condominium__isnull=not value)

    def filter_has_photos(self, queryset, name, value):
        photos = PropertyPhoto.objects.filter(property=OuterRef('pk'), deleted_at__isnull=True)

        return queryset.filter(Exists(photos)) if value else queryset.filter(~Exists(photos))


class DealFilter(filters.FilterSet):
    """Filtros do funil: o quadro pede só os negócios em jogo, a lista de encerrados só o resto."""

    is_open = filters.BooleanFilter(field_name='outcome', lookup_expr='isnull')

    class Meta:
        model = Deal
        fields = ['stage', 'outcome', 'type', 'responsible']


def overdue_tasks_condition(now=None):
    """Tarefa pendente cujo prazo já passou; a mesma regra do `is_overdue` do serializer."""
    now = now or timezone.localtime()
    past_due = Q(due_date__lt=now.date()) | Q(
        due_date=now.date(), due_time__isnull=False, due_time__lt=now.time()
    )

    return ~Q(status=Task.Status.DONE) & past_due


class TaskFilter(filters.FilterSet):
    """Filtros da lista e da agenda de tarefas, para a tela não precisar da base inteira."""

    overdue = filters.BooleanFilter(method='filter_overdue')
    due_date_from = filters.DateFilter(field_name='due_date', lookup_expr='gte')
    due_date_to = filters.DateFilter(field_name='due_date', lookup_expr='lte')

    class Meta:
        model = Task
        fields = ['status', 'priority', 'type', 'due_date', 'responsible', 'lead', 'deal']

    def filter_overdue(self, queryset, name, value):
        condition = overdue_tasks_condition()

        return queryset.filter(condition) if value else queryset.exclude(condition)
