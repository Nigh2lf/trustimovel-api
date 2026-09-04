from io import BytesIO
from pathlib import PurePosixPath

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageOps


FORMAT_EXTENSIONS = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}


def output_format():
    """Formato único de armazenamento das fotos, definido em PROPERTY_PHOTO_FORMAT."""
    image_format = settings.PROPERTY_PHOTO_FORMAT.upper()

    return image_format, FORMAT_EXTENSIONS.get(image_format, f'.{image_format.lower()}')


def resize_upload(uploaded_file, *, max_side: int = None):
    """Reduz a imagem pelo maior lado e regrava no formato de saída, com qualidade menor."""
    max_side = max_side or settings.PROPERTY_PHOTO_MAX_SIDE
    image_format, extension = output_format()
    image = ImageOps.exif_transpose(Image.open(uploaded_file))

    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.LANCZOS)

    if image.mode in ('P', 'CMYK'):
        image = image.convert('RGB' if image_format == 'JPEG' else 'RGBA')
    elif image_format == 'JPEG' and image.mode not in ('RGB', 'L'):
        # Só o JPEG não aceita canal alfa; WEBP e PNG guardam a transparência.
        image = image.convert('RGB')

    buffer = BytesIO()
    image.save(
        buffer, format=image_format, quality=settings.PROPERTY_PHOTO_QUALITY, optimize=True
    )

    name = str(PurePosixPath(uploaded_file.name).with_suffix(extension))

    return ContentFile(buffer.getvalue(), name=name)


def thumbnail_name(image_name: str) -> str:
    path = PurePosixPath(image_name)

    return str(path.parent / f'mini-{path.name}')


def build_thumbnail(photo):
    """Grava a miniatura ao lado da original, como mini-<nome_da_foto>."""
    name = thumbnail_name(photo.image.name)
    storage = photo.image.storage

    with photo.image.open('rb') as original:
        content = resize_upload(original, max_side=settings.PROPERTY_PHOTO_THUMBNAIL_SIDE)

    # Apaga antes para o storage não renomear o arquivo ao encontrar um homônimo.
    storage.delete(name)
    storage.save(name, content)

    return name


def delete_thumbnail(photo):
    if photo.image:
        photo.image.storage.delete(thumbnail_name(photo.image.name))


def replace_thumbnail(photo, previous_main=None):
    if previous_main is not None:
        delete_thumbnail(previous_main)

    return build_thumbnail(photo)


def promote_next_main(parent):
    """Elege a primeira foto restante da galeria como miniatura do imóvel ou condomínio."""
    next_main = (
        parent.photos.filter(deleted_at__isnull=True)
        .order_by('position', 'created_at')
        .first()
    )

    if next_main is None:
        return None

    next_main.is_main = True
    next_main.save(update_fields=['is_main'])
    build_thumbnail(next_main)

    return next_main


def delete_photo(photo, *, promote=True):
    """Apaga os arquivos do disco, marca a foto como excluída e reelege a miniatura."""
    was_main = photo.is_main

    if was_main:
        delete_thumbnail(photo)

    # Apaga direto no storage para o registro manter o nome do arquivo que existia.
    if photo.image:
        photo.image.storage.delete(photo.image.name)

    photo.is_main = False
    photo.delete()

    # Ao esvaziar a galeria inteira não faz sentido eleger uma miniatura a cada foto apagada.
    return promote_next_main(photo.parent) if was_main and promote else None
