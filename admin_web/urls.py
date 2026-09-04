from rest_framework.routers import DefaultRouter

from .views import (
    AdminUserViewSet,
    AgencyViewSet,
    CityViewSet,
    CountryViewSet,
    ExporterPlanViewSet,
    ExporterViewSet,
    FeatureViewSet,
    FeeViewSet,
    NeighborhoodViewSet,
    PlanViewSet,
    PropertyTypeViewSet,
    StateViewSet,
)

router = DefaultRouter()
router.register(r'agencies', AgencyViewSet, basename='admin-agency')
router.register(r'plans', PlanViewSet, basename='admin-plan')
router.register(r'users', AdminUserViewSet, basename='admin-user')
router.register(r'property-types', PropertyTypeViewSet, basename='admin-property-type')
router.register(r'features', FeatureViewSet, basename='admin-feature')
router.register(r'fees', FeeViewSet, basename='admin-fee')
router.register(r'exporters', ExporterViewSet, basename='admin-exporter')
router.register(r'exporter-plans', ExporterPlanViewSet, basename='admin-exporter-plan')
router.register(r'countries', CountryViewSet, basename='admin-country')
router.register(r'states', StateViewSet, basename='admin-state')
router.register(r'cities', CityViewSet, basename='admin-city')
router.register(r'neighborhoods', NeighborhoodViewSet, basename='admin-neighborhood')

urlpatterns = router.urls
