from pathlib import Path

from django.conf import settings
from rest_framework import serializers

from core.models import CompanySection, SiteBanner
from core.services.photos import resize_upload


class SiteImageSerializer(serializers.ModelSerializer):
    """Base do conteúdo do site: título obrigatório e uma imagem por registro."""

    def validate_title(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError("Informe o título.")

        return value

    def validate_image(self, value):
        max_megabytes = settings.PROPERTY_PHOTO_MAX_UPLOAD_MB

        if value.size > max_megabytes * 1024 * 1024:
            raise serializers.ValidationError(
                f"A imagem deve ter no máximo {max_megabytes} MB."
            )

        extensions = settings.PROPERTY_PHOTO_ALLOWED_EXTENSIONS

        if Path(value.name).suffix.lower() not in extensions:
            aceitos = ", ".join(extension.lstrip(".").upper() for extension in extensions)
            raise serializers.ValidationError(f"Formato não aceito. Envie {aceitos}.")

        return value

    def create(self, validated_data):
        self._resize_image(validated_data)

        return super().create(validated_data)

    def update(self, instance, validated_data):
        self._resize_image(validated_data)
        replaced_image = instance.image.name if validated_data.get("image") and instance.image else None
        instance = super().update(instance, validated_data)

        # O registro guarda uma imagem só, então a anterior não tem mais como ser exibida.
        if replaced_image:
            instance.image.storage.delete(replaced_image)

        return instance

    def _resize_image(self, validated_data):
        if validated_data.get("image"):
            validated_data["image"] = resize_upload(
                validated_data["image"], max_side=settings.SITE_IMAGE_MAX_SIDE
            )


class CompanySectionSerializer(SiteImageSerializer):
    class Meta:
        model = CompanySection
        fields = ["id", "title", "text", "image"]
        read_only_fields = ("id",)


class SiteBannerSerializer(SiteImageSerializer):
    class Meta:
        model = SiteBanner
        fields = ["id", "title", "link", "image", "is_active"]
        read_only_fields = ("id",)
