from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from core.serializers.user import permission_map

User = get_user_model()


class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = {
            "id": self.user.id,
            "email": self.user.email,
            "name": self.user.name,
            "type": self.user.type,
            # O menu é montado no primeiro render depois do login; sem isso a tela
            # precisaria de uma segunda chamada antes de saber o que mostrar.
            "permissions": permission_map(self.user),
        }
        return data


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ChangePasswordForgotSerializer(serializers.Serializer):
    email = serializers.EmailField()
    forgot_password_hash = serializers.CharField()
    new_password = serializers.CharField(write_only=True)


class ChangePasswordSerializer(serializers.Serializer):
    """
    Usado quando o usuário JÁ está logado e quer trocar a senha.
    """

    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)

    def validate_new_password(self, value):
        validate_password(value)
        return value

    def validate(self, data):
        user = self.context["request"].user
        if not user.check_password(data["old_password"]):
            raise serializers.ValidationError(
                {"old_password": "A senha atual está incorreta."}
            )
        return data
