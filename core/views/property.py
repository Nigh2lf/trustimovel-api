from django.db.models import Case, Count, F, IntegerField, OuterRef, Prefetch, Q, Subquery, Value, When
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.classes.base_viewset import BaseViewSet
from core.classes.permission_resource import ResourcePermission
from core.classes.permission_type_user import AdminPermissionClass, AllPermissionClass
from core.filters import CityFilter, NeighborhoodFilter, PropertyFilter, StateFilter
from core.resources import AccessLevel, requires_level
from core.models import (
    AgencyExporter,
    AgencyExporterPlan,
    Broker,
    City,
    Client,
    Condominium,
    CondominiumPhoto,
    Country,
    Exporter,
    Feature,
    Fee,
    Neighborhood,
    Owner,
    Property,
    PropertyHistory,
    PropertyPhoto,
    PropertyPrice,
    PropertyType,
    State,
)
from core.services.photos import delete_photo
from core.services.property_history import record, record_update, snapshot
from core.serializers import (
    AgencyExporterSerializer,
    BrokerSerializer,
    CitySerializer,
    ClientSerializer,
    CondominiumPhotoBulkDeleteSerializer,
    CondominiumPhotoReorderSerializer,
    CondominiumPhotoSerializer,
    CondominiumSerializer,
    CountrySerializer,
    ExporterSerializer,
    FeatureSerializer,
    FeeSerializer,
    NeighborhoodSerializer,
    OwnerSerializer,
    PropertyHistorySerializer,
    PropertyPhotoBulkDeleteSerializer,
    PropertyPhotoReorderSerializer,
    PropertyPhotoSerializer,
    PropertySerializer,
    PropertyTypeSerializer,
    StateSerializer,
)


PURPOSE_PRIORITY = Case(
    When(purpose=PropertyPrice.Purpose.SALE, then=Value(0)),
    When(purpose=PropertyPrice.Purpose.RENT, then=Value(1)),
    default=Value(2),
    output_field=IntegerField(),
)


class NullsLastOrderingFilter(OrderingFilter):
    """Manda o registro sem valor no campo ordenado para o fim, nas duas direções."""

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)

        if not ordering:
            return queryset

        return queryset.order_by(*[self._term(field) for field in ordering])

    def _term(self, field):
        if field.startswith('-'):
            return F(field[1:]).desc(nulls_last=True)

        return F(field).asc(nulls_last=True)


class GlobalCatalogViewSet(BaseViewSet):
    """Catálogo compartilhado por todas as imobiliárias: qualquer usuário lê, só ADMIN altera."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    model = None

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]

        return [permissions.IsAuthenticated(), AdminPermissionClass()]

    def get_queryset(self):
        return self.model.objects.filter(deleted_at__isnull=True)


class AgencyScopedViewSet(BaseViewSet):
    """Restringe todo acesso aos registros da imobiliária do usuário autenticado.

    Cada subclasse declara o `resource` do catálogo (`core/resources.py`); a partir dele o
    `ResourcePermission` exige o nível correspondente à action.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, AllPermissionClass, ResourcePermission]
    resource = None
    model = None

    def get_queryset(self):
        return self.model.objects.filter(
            agency_id=self.request.user.agency_id,
            deleted_at__isnull=True,
        )

    def perform_create(self, serializer):
        serializer.save(agency_id=self.request.user.agency_id)


class CountryViewSet(GlobalCatalogViewSet):
    model = Country
    serializer_class = CountrySerializer
    search_fields = ["name", "code"]
    ordering_fields = ("name", "code")
    ordering = ("name",)


class StateViewSet(GlobalCatalogViewSet):
    model = State
    serializer_class = StateSerializer
    search_fields = ["name", "abbreviation"]
    filterset_class = StateFilter
    ordering_fields = ("name", "abbreviation")
    ordering = ("name",)


class CityViewSet(GlobalCatalogViewSet):
    model = City
    serializer_class = CitySerializer
    search_fields = ["name"]
    filterset_class = CityFilter
    ordering_fields = ("name", "ibge_code", "state__name")
    ordering = ("name",)

    def get_queryset(self):
        return super().get_queryset().select_related("state")


class NeighborhoodViewSet(GlobalCatalogViewSet):
    model = Neighborhood
    serializer_class = NeighborhoodSerializer
    search_fields = ["name"]
    filterset_class = NeighborhoodFilter
    ordering_fields = ("name", "city__name")
    ordering = ("name",)

    def get_queryset(self):
        return super().get_queryset().select_related("city")


class CatalogPagination(PageNumberPagination):
    # Catálogo pequeno e fechado: a tela de cadastro precisa dele inteiro de uma vez.
    page_size = 200


class PropertyTypeViewSet(GlobalCatalogViewSet):
    model = PropertyType
    serializer_class = PropertyTypeSerializer
    pagination_class = CatalogPagination
    search_fields = ["name"]
    ordering_fields = ("name",)
    ordering = ("name",)


class FeatureViewSet(GlobalCatalogViewSet):
    model = Feature
    serializer_class = FeatureSerializer
    pagination_class = CatalogPagination
    search_fields = ["name"]
    filterset_fields = ["type"]
    ordering_fields = ("name", "type")
    ordering = ("name",)


class FeeViewSet(GlobalCatalogViewSet):
    model = Fee
    serializer_class = FeeSerializer
    pagination_class = CatalogPagination
    search_fields = ["name"]
    ordering_fields = ("name",)
    ordering = ("name",)


class ExporterViewSet(GlobalCatalogViewSet):
    model = Exporter
    serializer_class = ExporterSerializer
    pagination_class = CatalogPagination
    search_fields = ["name"]
    ordering_fields = ("name",)
    ordering = ("name",)

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True).prefetch_related("plans")


class AgencyExporterViewSet(AgencyScopedViewSet):
    resource = 'exportadores'
    model = AgencyExporter
    serializer_class = AgencyExporterSerializer
    # Lista fechada e pequena: o cadastro de imóvel precisa dela inteira de uma vez.
    pagination_class = CatalogPagination
    search_fields = ["exporter__name"]
    filter_backends = (SearchFilter, OrderingFilter)
    ordering_fields = ("exporter__name", "exported")
    ordering = ("exporter__name",)

    def get_queryset(self):
        agency_id = self.request.user.agency_id

        # Imóvel excluído não conta como exportado, igual ao que a listagem de imóveis mostra.
        plans = AgencyExporterPlan.objects.select_related("plan").annotate(
            used=Count(
                "plan__properties",
                filter=Q(
                    plan__properties__property__agency_id=agency_id,
                    plan__properties__property__deleted_at__isnull=True,
                ),
            )
        )

        # A configuração não tem exclusão lógica, então não filtra deleted_at como a base.
        return (
            AgencyExporter.objects.filter(agency_id=agency_id)
            .select_related("exporter")
            .prefetch_related(Prefetch("plans", queryset=plans))
            .annotate(
                exported=Count(
                    "exporter__properties",
                    filter=Q(
                        exporter__properties__property__agency_id=agency_id,
                        exporter__properties__property__deleted_at__isnull=True,
                    ),
                )
            )
        )

    def perform_destroy(self, instance):
        instance.delete()


class CondominiumViewSet(AgencyScopedViewSet):
    resource = 'condominios'
    model = Condominium
    serializer_class = CondominiumSerializer
    search_fields = ["name", "neighborhood__name"]
    filter_backends = (SearchFilter, OrderingFilter)
    ordering_fields = ("name", "address", "neighborhood__name", "created_at")
    ordering = ("name",)

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("neighborhood__city__state__country")
            .prefetch_related("features")
        )


class BrokerViewSet(AgencyScopedViewSet):
    resource = 'corretores'
    model = Broker
    serializer_class = BrokerSerializer
    search_fields = ["name", "email", "phone"]
    filter_backends = (SearchFilter, OrderingFilter)
    ordering_fields = ("name", "email", "phone", "created_at")
    ordering = ("name",)


class OwnerViewSet(AgencyScopedViewSet):
    resource = 'proprietarios'
    model = Owner
    serializer_class = OwnerSerializer
    search_fields = ["name", "email", "phone"]
    filter_backends = (SearchFilter, OrderingFilter)
    ordering_fields = ("name", "email", "phone", "created_at")
    ordering = ("name",)


class ClientViewSet(AgencyScopedViewSet):
    resource = 'clientes'
    model = Client
    serializer_class = ClientSerializer
    search_fields = ["code", "name", "email", "phone", "document"]
    filterset_fields = ["type", "is_active"]
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    ordering_fields = (
        "code",
        "name",
        "email",
        "phone",
        "type",
        "is_active",
        "neighborhood__city__name",
        "created_at",
    )
    ordering = ("name",)

    def get_queryset(self):
        return super().get_queryset().select_related("neighborhood__city__state__country")


class PropertyViewSet(AgencyScopedViewSet):
    resource = 'imoveis'
    model = Property
    serializer_class = PropertySerializer
    filterset_class = PropertyFilter
    search_fields = [
        "name",
        "description",
        "address",
        "owner_name",
        "neighborhood__name",
        "neighborhood__city__name",
        "condominium__name",
    ]
    filter_backends = (DjangoFilterBackend, SearchFilter, NullsLastOrderingFilter)
    ordering_fields = (
        "code",
        "name",
        "price",
        "area",
        "bedrooms",
        "views_count",
        "type__name",
        "neighborhood__name",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(price=self._reference_price())
            .select_related(
                "type",
                "condominium",
                "neighborhood__city__state",
                "broker",
                # A ficha do proprietário lê até o país; sem isso são quatro consultas por imóvel.
                "owner__neighborhood__city__state__country",
            )
            .prefetch_related(
                # Foto excluída não pode voltar na listagem pelo relacionamento.
                Prefetch("photos", queryset=PropertyPhoto.objects.filter(deleted_at__isnull=True)),
                "prices",
                "fees",
                "features",
                "exporters",
            )
        )

    def perform_create(self, serializer):
        super().perform_create(serializer)
        record(serializer.instance, self.request.user, PropertyHistory.Action.CREATED)

    def perform_update(self, serializer):
        # O retrato precisa sair antes do save; depois os valores antigos já se perderam.
        before = snapshot(serializer.instance)
        super().perform_update(serializer)
        record_update(serializer.instance, self.request.user, before)

    @action(detail=True, methods=["get"])
    @requires_level(AccessLevel.READ)
    def history(self, request, pk=None):
        instance = self.get_object()
        entries = instance.history.select_related("user")
        data = PropertyHistorySerializer(entries, many=True).data

        return self._response_format(True, status.HTTP_200_OK, data=data)

    def _reference_price(self):
        """Valor que a ordenação usa: o da finalidade filtrada, ou o de venda quando não houver."""
        prices = PropertyPrice.objects.filter(property=OuterRef("pk"))
        purpose = self.request.query_params.get("purpose")

        if purpose in PropertyPrice.Purpose.values:
            prices = prices.filter(purpose=purpose).order_by()
        else:
            prices = prices.annotate(priority=PURPOSE_PRIORITY).order_by("priority")

        return Subquery(prices.values("amount")[:1])


class PhotoPagination(PageNumberPagination):
    # A galeria é sempre pequena e a tela precisa dela inteira para reordenar.
    page_size = 100


class PhotoViewSet(BaseViewSet):
    """Base das galerias de imóvel e de condomínio, restrita à imobiliária do usuário.

    A galeria não é uma tela do menu: ela herda o recurso do dono, então quem edita imóvel
    edita as fotos do imóvel e quem só lê imóvel só vê as fotos.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, AllPermissionClass, ResourcePermission]
    pagination_class = PhotoPagination
    resource = None
    model = None
    bulk_delete_serializer_class = None
    reorder_serializer_class = None

    def get_queryset(self):
        parent_field = self.model.parent_field

        return self.model.objects.filter(
            **{
                f"{parent_field}__agency_id": self.request.user.agency_id,
                f"{parent_field}__deleted_at__isnull": True,
                "deleted_at__isnull": True,
            }
        )

    def perform_create(self, serializer):
        super().perform_create(serializer)
        self.log_photo_action(serializer.instance.parent, PropertyHistory.Action.PHOTOS_ADDED)

    def perform_destroy(self, instance):
        parent = instance.parent
        # O registro fica marcado como excluído, mas o arquivo sai da pasta.
        delete_photo(instance)
        self.log_photo_action(parent, PropertyHistory.Action.PHOTOS_REMOVED)

    def log_photo_action(self, parent, action, notes=''):
        """Só a galeria do imóvel tem histórico; a do condomínio não registra nada."""

    @action(detail=False, methods=["post"], url_path="delete-all")
    @requires_level(AccessLevel.FULL)
    def delete_all(self, request):
        serializer = self.bulk_delete_serializer_class(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        photos = serializer.save()

        if photos:
            self.log_photo_action(
                photos[0].parent,
                PropertyHistory.Action.PHOTOS_REMOVED,
                notes=f'{len(photos)} imagem(ns) removida(s).',
            )

        return self._response_format(
            True,
            status.HTTP_200_OK,
            message=f"{len(photos)} foto(s) removida(s).",
            data={"deleted": len(photos)},
        )

    @action(detail=False, methods=["post"])
    @requires_level(AccessLevel.WRITE)
    def reorder(self, request):
        serializer = self.reorder_serializer_class(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        photos = serializer.save()

        if photos:
            self.log_photo_action(photos[0].parent, PropertyHistory.Action.PHOTOS_REORDERED)

        data = self.serializer_class(
            photos, many=True, context=self.get_serializer_context()
        ).data

        return self._response_format(True, status.HTTP_200_OK, data=data)


class PropertyPhotoViewSet(PhotoViewSet):
    resource = 'imoveis'
    model = PropertyPhoto
    serializer_class = PropertyPhotoSerializer
    bulk_delete_serializer_class = PropertyPhotoBulkDeleteSerializer
    reorder_serializer_class = PropertyPhotoReorderSerializer
    filterset_fields = ["property"]

    def log_photo_action(self, parent, action, notes=''):
        record(parent, self.request.user, action, notes=notes)


class CondominiumPhotoViewSet(PhotoViewSet):
    resource = 'condominios'
    model = CondominiumPhoto
    serializer_class = CondominiumPhotoSerializer
    bulk_delete_serializer_class = CondominiumPhotoBulkDeleteSerializer
    reorder_serializer_class = CondominiumPhotoReorderSerializer
    filterset_fields = ["condominium"]
