import re

from rest_framework import serializers

from core.models import AgencySettings

HEX_COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')


class AgencySettingsSerializer(serializers.ModelSerializer):
    # A chave secreta nunca volta ao navegador; a tela só sabe se existe uma gravada.
    recaptcha_secret_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=100
    )
    has_recaptcha_secret_key = serializers.SerializerMethodField()

    class Meta:
        model = AgencySettings
        fields = [
            'id',
            'system_name',
            'site_url',
            'site_description',
            'contact_email',
            'phone',
            'whatsapp',
            'address',
            'sender_email',
            'sender_name',
            'cc_email',
            'primary_color',
            'secondary_color',
            'logo_url',
            'favicon_url',
            'google_analytics_id',
            'google_maps_key',
            'recaptcha_site_key',
            'recaptcha_secret_key',
            'has_recaptcha_secret_key',
            'facebook_url',
            'instagram_url',
            'property_code_auto_increment',
            'property_code_prefix',
            'updated_at',
        ]
        read_only_fields = ('id', 'updated_at', 'has_recaptcha_secret_key')

    def get_has_recaptcha_secret_key(self, settings):
        return bool(settings.recaptcha_secret_key)

    def validate_primary_color(self, value):
        return self._validate_color(value)

    def validate_secondary_color(self, value):
        return self._validate_color(value)

    def _validate_color(self, value):
        if not HEX_COLOR_PATTERN.match(value):
            raise serializers.ValidationError('Informe a cor no formato hexadecimal, ex.: #003533.')

        return value
