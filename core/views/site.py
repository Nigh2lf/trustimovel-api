from rest_framework.filters import OrderingFilter, SearchFilter

from core.models import CompanySection, SiteBanner
from core.serializers import CompanySectionSerializer, SiteBannerSerializer
from core.views.property import AgencyScopedViewSet


class CompanySectionViewSet(AgencyScopedViewSet):
    resource = 'empresa'
    model = CompanySection
    serializer_class = CompanySectionSerializer
    search_fields = ["title", "text"]
    filter_backends = (SearchFilter, OrderingFilter)
    ordering_fields = ("title", "created_at")
    ordering = ("title",)


class SiteBannerViewSet(AgencyScopedViewSet):
    resource = 'banners'
    model = SiteBanner
    serializer_class = SiteBannerSerializer
    search_fields = ["title", "link"]
    filter_backends = (SearchFilter, OrderingFilter)
    ordering_fields = ("title", "link", "is_active", "created_at")
    ordering = ("title",)
