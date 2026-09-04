from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Roda antes do import dos serializers, que fixam as mensagens ao declarar os campos.
        from core.api_messages import apply_portuguese_messages

        apply_portuguese_messages()
