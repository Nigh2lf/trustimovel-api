import json

from django.utils.text import slugify
from rest_framework import serializers

from core.models import BlogCategory, BlogPost
from core.serializers.site import SiteImageSerializer


class TagsField(serializers.ListField):
    """Lista de tags que também aceita texto JSON, o único jeito de mandar lista vazia em multipart."""

    def to_internal_value(self, data):
        if len(data) == 1 and isinstance(data[0], str) and data[0].startswith("["):
            try:
                data = json.loads(data[0])
            except ValueError:
                raise serializers.ValidationError("Não foi possível ler a lista de tags.")

        return super().to_internal_value(data)


class BlogCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogCategory
        fields = ["id", "name"]
        read_only_fields = ("id",)

    def validate_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError("Informe o nome da categoria.")

        return value


class BlogPostSerializer(SiteImageSerializer):
    """Matéria do blog: reaproveita a validação e o redimensionamento da imagem do site."""

    category_name = serializers.CharField(source="category.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    tags = TagsField(
        child=serializers.CharField(max_length=40),
        required=False,
        allow_empty=True,
    )

    class Meta:
        model = BlogPost
        fields = [
            "id",
            "category",
            "category_name",
            "title",
            "slug",
            "published_at",
            "image",
            "youtube_url",
            "description",
            "meta_title",
            "meta_description",
            "tags",
            "status",
            "status_label",
        ]
        read_only_fields = ("id", "category_name", "status_label")

    def validate_category(self, value):
        # Categoria de outra imobiliária não pode ser usada, mesmo com o id certo.
        if value.agency_id != self.context["request"].user.agency_id:
            raise serializers.ValidationError("A categoria informada não está disponível.")

        if value.deleted_at is not None:
            raise serializers.ValidationError("A categoria informada foi excluída.")

        return value

    def validate(self, attrs):
        title = attrs.get("title", getattr(self.instance, "title", ""))
        # O model gera o endereço a partir do título só quando ele chega vazio.
        slug = attrs.get("slug") or getattr(self.instance, "slug", "") or slugify(title)[:180]

        duplicates = BlogPost.objects.filter(
            agency_id=self.context["request"].user.agency_id,
            slug=slug,
            deleted_at__isnull=True,
        )

        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        # O par (imobiliária, endereço) é único no banco; validar aqui devolve 400.
        if duplicates.exists():
            raise serializers.ValidationError(
                {"slug": "Já existe uma matéria com este endereço."}
            )

        return attrs
