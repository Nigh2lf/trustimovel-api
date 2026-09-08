import mimetypes

from storages.backends.s3boto3 import S3Boto3Storage

# O Python 3.10 do Windows não conhece .webp e gravaria a foto como application/octet-stream.
# Registrar aqui deixa o Content-Type igual em qualquer ambiente que use este storage.
mimetypes.add_type('image/webp', '.webp')


class MediaStorage(S3Boto3Storage):
    location = 'media'
    file_overwrite = False
    default_acl = None

    def path(self, name):
        return name

class StaticStorage(S3Boto3Storage):
    location = 'static'
    default_acl = None