"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from rest_framework import permissions
from rest_framework_simplejwt.views import TokenRefreshView
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from core.views import (
    ViewTokenObtainPair,
    UserViewSet,
    AddressLookupView,
    AssistantChatView,
    AssistantConversationViewSet,
    AssistantPropertySearchView,
    AgencyExporterViewSet,
    AgencySettingsView,
    BlogCategoryViewSet,
    BlogPostViewSet,
    DashboardView,
    QueueViewSet,
    ReportsView,
    DealViewSet,
    LeadViewSet,
    ServiceTicketViewSet,
    TaskViewSet,
    PropertyViewSet,
    PropertyPhotoViewSet,
    PropertyTypeViewSet,
    CondominiumViewSet,
    CondominiumPhotoViewSet,
    BrokerViewSet,
    OwnerViewSet,
    ClientViewSet,
    CompanySectionViewSet,
    SiteBannerViewSet,
    FeatureViewSet,
    FeeViewSet,
    ExporterViewSet,
    CountryViewSet,
    StateViewSet,
    CityViewSet,
    NeighborhoodViewSet,
)

schema_view = get_schema_view(
    openapi.Info(
        title="API",
        default_version='v1',
        description="API documentation",
        contact=openapi.Contact(email="noclaf@noclaf.com"),
        license=openapi.License(name="BSD License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'queue', QueueViewSet, basename='queue')
router.register(r'assistant/conversations', AssistantConversationViewSet, basename='assistant-conversation')
router.register(r'leads', LeadViewSet, basename='lead')
router.register(r'service-tickets', ServiceTicketViewSet, basename='service-ticket')
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'deals', DealViewSet, basename='deal')
router.register(r'properties', PropertyViewSet, basename='property')
router.register(r'property-photos', PropertyPhotoViewSet, basename='property-photo')
router.register(r'property-types', PropertyTypeViewSet, basename='property-type')
router.register(r'condominiums', CondominiumViewSet, basename='condominium')
router.register(r'condominium-photos', CondominiumPhotoViewSet, basename='condominium-photo')
router.register(r'brokers', BrokerViewSet, basename='broker')
router.register(r'owners', OwnerViewSet, basename='owner')
router.register(r'clients', ClientViewSet, basename='client')
router.register(r'blog-categories', BlogCategoryViewSet, basename='blog-category')
router.register(r'blog-posts', BlogPostViewSet, basename='blog-post')
router.register(r'company-sections', CompanySectionViewSet, basename='company-section')
router.register(r'site-banners', SiteBannerViewSet, basename='site-banner')
router.register(r'features', FeatureViewSet, basename='feature')
router.register(r'fees', FeeViewSet, basename='fee')
router.register(r'exporters', ExporterViewSet, basename='exporter')
router.register(r'agency-exporters', AgencyExporterViewSet, basename='agency-exporter')
router.register(r'countries', CountryViewSet, basename='country')
router.register(r'states', StateViewSet, basename='state')
router.register(r'cities', CityViewSet, basename='city')
router.register(r'neighborhoods', NeighborhoodViewSet, basename='neighborhood')

urlpatterns = [
    path('', include(router.urls)),
    path('admin/', admin.site.urls),

    # Painel administrativo: tudo aqui exige usuário ADMIN (ver app admin_web).
    path('admin-web/', include('admin_web.urls')),

    path('addresses/lookup/', AddressLookupView.as_view(), name='address_lookup'),
    path('assistant/chat/', AssistantChatView.as_view(), name='assistant_chat'),
    path('assistant/property-search/', AssistantPropertySearchView.as_view(), name='assistant_property_search'),
    path('agency-settings/', AgencySettingsView.as_view(), name='agency_settings'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('reports/', ReportsView.as_view(), name='reports'),

    path('auth-user/', ViewTokenObtainPair.as_view(), name='token_obtain_pair'),
    path('token-refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


# Definição de segurança JWT para o Swagger (Token JWT - Bearer)
schema_view.security_definitions = {
    'Bearer': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'Authorization',
        'description': 'JWT Authorization header using the Bearer scheme. Example: "Bearer <token>"',
    }
}
