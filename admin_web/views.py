from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.classes.base_viewset import BaseViewSet
from core.classes.permission_type_user import AdminPermissionClass
from core.models import (
    Agency,
    City,
    Country,
    Exporter,
    ExporterPlan,
    Feature,
    Fee,
    Neighborhood,
    Plan,
    PropertyType,
    State,
    User,
)
from core.serializers import (
    CountrySerializer,
    ExporterSerializer,
    FeatureSerializer,
    FeeSerializer,
    NeighborhoodSerializer,
    PropertyTypeSerializer,
)

from .serializers import (
    AdminCitySerializer,
    AdminExporterPlanSerializer,
    AdminStateSerializer,
    AdminUserSerializer,
    AgencySerializer,
    PlanSerializer,
)


class AdminViewSet(BaseViewSet):
    """Base de todo recurso do painel administrativo: só entra quem tem perfil ADMIN."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, AdminPermissionClass]
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    model = None

    def get_queryset(self):
        return self.model.objects.filter(deleted_at__isnull=True)


class PlanViewSet(AdminViewSet):
    model = Plan
    serializer_class = PlanSerializer
    search_fields = ["name"]
    ordering_fields = ("name", "property_limit", "photo_limit")
    ordering = ("name",)


class AgencyViewSet(AdminViewSet):
    model = Agency
    serializer_class = AgencySerializer
    search_fields = ["name", "email", "phone"]
    filterset_fields = ["is_active", "plan"]
    ordering_fields = ("name", "email", "phone", "is_active", "plan__name", "created_at")
    ordering = ("name",)

    def get_queryset(self):
        return super().get_queryset().select_related("plan")


class AdminUserViewSet(AdminViewSet):
    model = User
    serializer_class = AdminUserSerializer
    search_fields = ["email", "name"]
    filterset_fields = ["type", "agency", "is_active"]
    ordering_fields = ("email", "name", "type", "is_active", "agency__name", "created_at")
    ordering = ("email",)

    def get_queryset(self):
        return super().get_queryset().select_related("agency")


class PropertyTypeViewSet(AdminViewSet):
    model = PropertyType
    serializer_class = PropertyTypeSerializer
    search_fields = ["name"]
    ordering_fields = ("name",)
    ordering = ("name",)


class FeatureViewSet(AdminViewSet):
    model = Feature
    serializer_class = FeatureSerializer
    search_fields = ["name"]
    filterset_fields = ["type"]
    ordering_fields = ("name", "type")
    ordering = ("name",)


class FeeViewSet(AdminViewSet):
    model = Fee
    serializer_class = FeeSerializer
    search_fields = ["name"]
    ordering_fields = ("name",)
    ordering = ("name",)


class ExporterViewSet(AdminViewSet):
    model = Exporter
    serializer_class = ExporterSerializer
    search_fields = ["name"]
    filterset_fields = ["is_active"]
    ordering_fields = ("name", "slug", "is_active")
    ordering = ("name",)

    def get_queryset(self):
        return super().get_queryset().prefetch_related("plans")


class ExporterPlanViewSet(AdminViewSet):
    model = ExporterPlan
    serializer_class = AdminExporterPlanSerializer
    search_fields = ["name"]
    filterset_fields = ["exporter"]
    ordering_fields = ("name", "position", "exporter__name")
    ordering = ("exporter__name", "position", "name")

    def get_queryset(self):
        # O plano é o único cadastro daqui sem exclusão lógica: ele some junto com o exportador.
        return ExporterPlan.objects.select_related("exporter")

    def perform_destroy(self, instance):
        instance.delete()


class CountryViewSet(AdminViewSet):
    model = Country
    serializer_class = CountrySerializer
    search_fields = ["name", "code"]
    ordering_fields = ("name", "code")
    ordering = ("name",)


class StateViewSet(AdminViewSet):
    model = State
    serializer_class = AdminStateSerializer
    search_fields = ["name", "abbreviation"]
    filterset_fields = ["country"]
    ordering_fields = ("name", "abbreviation", "country__name")
    ordering = ("name",)

    def get_queryset(self):
        return super().get_queryset().select_related("country")


class CityViewSet(AdminViewSet):
    model = City
    serializer_class = AdminCitySerializer
    search_fields = ["name", "ibge_code"]
    filterset_fields = ["state"]
    ordering_fields = ("name", "ibge_code", "state__name")
    ordering = ("name",)

    def get_queryset(self):
        return super().get_queryset().select_related("state")


class NeighborhoodViewSet(AdminViewSet):
    model = Neighborhood
    serializer_class = NeighborhoodSerializer
    search_fields = ["name"]
    filterset_fields = ["city"]
    ordering_fields = ("name", "city__name", "city__state__abbreviation")
    ordering = ("name",)

    def get_queryset(self):
        return super().get_queryset().select_related("city")
