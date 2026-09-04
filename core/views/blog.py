from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter

from core.models import BlogCategory, BlogPost
from core.serializers import BlogCategorySerializer, BlogPostSerializer
from core.views.property import AgencyScopedViewSet, CatalogPagination


class BlogCategoryViewSet(AgencyScopedViewSet):
    resource = 'blog_categorias'
    model = BlogCategory
    serializer_class = BlogCategorySerializer
    # Lista fechada e pequena: o formulário da matéria precisa dela inteira de uma vez.
    pagination_class = CatalogPagination
    search_fields = ["name"]
    filter_backends = (SearchFilter, OrderingFilter)
    ordering_fields = ("name", "created_at")
    ordering = ("name",)


class BlogPostViewSet(AgencyScopedViewSet):
    resource = 'blog'
    model = BlogPost
    serializer_class = BlogPostSerializer
    search_fields = ["title", "description"]
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    filterset_fields = ["category", "status"]
    ordering_fields = ("title", "category__name", "status", "published_at", "created_at")
    ordering = ("-published_at", "-created_at")

    def get_queryset(self):
        return super().get_queryset().select_related("category")
