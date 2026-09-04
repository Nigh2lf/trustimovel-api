from django.contrib.auth.password_validation import validate_password
from django.utils.text import slugify
from rest_framework import serializers

from core.models import Agency, ExporterPlan, Plan, User
from core.serializers import CitySerializer, ExporterPlanSerializer, StateSerializer
from core.services import grant_full_access


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "id",
            "name",
            "property_limit",
            "photo_limit",
            "created_at",
        ]
        read_only_fields = ("id", "created_at")


class AgencySerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True, allow_null=True)

    class Meta:
        model = Agency
        fields = [
            "id",
            "name",
            "slug",
            "site",
            "phone",
            "email",
            "plan",
            "plan_name",
            "is_active",
            "created_at",
        ]
        read_only_fields = ("id", "plan_name", "created_at")

    def validate(self, attrs):
        name = attrs.get("name", getattr(self.instance, "name", ""))
        # O model gera o slug a partir do nome só quando ele chega vazio.
        slug = attrs.get("slug") or getattr(self.instance, "slug", "") or slugify(name)

        duplicates = Agency.objects.filter(slug=slug)

        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        # O slug é único no banco; validar aqui devolve 400 em vez de erro interno.
        if duplicates.exists():
            raise serializers.ValidationError(
                {"name": "Já existe uma imobiliária com este nome."}
            )

        return attrs


class AdminUserSerializer(serializers.ModelSerializer):
    """Usuário visto pelo administrador: aqui a imobiliária e o perfil de acesso são editáveis."""

    password = serializers.CharField(write_only=True, required=False)
    agency_name = serializers.CharField(source="agency.name", read_only=True, allow_null=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "name",
            "agency",
            "agency_name",
            "type",
            "is_active",
            "password",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "agency_name", "created_at", "updated_at")

    def validate_password(self, value):
        validate_password(value)

        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)

        if not password:
            raise serializers.ValidationError({"password": "Informe a senha do usuário."})

        user = User(**validated_data)
        user.set_password(password)
        user.save()

        # Quem nasce pelo painel da plataforma é o dono da conta: sai com acesso a tudo,
        # senão a imobiliária receberia um usuário incapaz até de abrir o próprio menu.
        # Daí em diante é ele quem distribui as permissões da equipe.
        grant_full_access(user)

        return user

    def update(self, instance, validated_data):
        # O administrador redefine a senha sem precisar da senha atual do usuário.
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)

        if password:
            user.set_password(password)
            user.save(update_fields=["password"])

        return user


class AdminStateSerializer(StateSerializer):
    """O painel lista o estado com o país junto, sem uma requisição por linha."""

    country_name = serializers.CharField(source="country.name", read_only=True)

    class Meta(StateSerializer.Meta):
        fields = StateSerializer.Meta.fields + ["country_name"]


class AdminCitySerializer(CitySerializer):
    state_name = serializers.CharField(source="state.name", read_only=True)

    class Meta(CitySerializer.Meta):
        fields = CitySerializer.Meta.fields + ["state_name"]


class AdminExporterPlanSerializer(ExporterPlanSerializer):
    """Fora do exportador o plano precisa dizer a quem pertence."""

    exporter_name = serializers.CharField(source="exporter.name", read_only=True)

    class Meta(ExporterPlanSerializer.Meta):
        model = ExporterPlan
        fields = ExporterPlanSerializer.Meta.fields + ["exporter", "exporter_name"]
