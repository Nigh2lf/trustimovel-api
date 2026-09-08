from pathlib import Path

from django.conf import settings
from rest_framework import serializers


def validate_image_upload(value):
    """Tamanho e formato de toda imagem enviada pelo painel; devolve o arquivo validado."""
    max_megabytes = settings.PROPERTY_PHOTO_MAX_UPLOAD_MB

    if value.size > max_megabytes * 1024 * 1024:
        raise serializers.ValidationError(f"A imagem deve ter no máximo {max_megabytes} MB.")

    extensions = settings.PROPERTY_PHOTO_ALLOWED_EXTENSIONS

    if Path(value.name).suffix.lower() not in extensions:
        aceitos = ", ".join(extension.lstrip(".").upper() for extension in extensions)
        raise serializers.ValidationError(f"Formato não aceito. Envie {aceitos}.")

    return value


def image_url(image, request=None):
    """URL de um ImageField, absoluta quando há requisição; None quando não há arquivo."""
    if not image:
        return None

    url = image.url

    return request.build_absolute_uri(url) if request is not None else url
