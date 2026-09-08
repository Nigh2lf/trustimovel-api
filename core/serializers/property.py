from django.conf import settings
from django.utils.text import slugify
from rest_framework import serializers

from core.serializers.images import validate_image_upload
from core.models import (
    AgencyExporter,
    AgencyExporterPlan,
    Broker,
    City,
    Client,
    Condominium,
    CondominiumPhoto,
    Country,
    Exporter,
    ExporterPlan,
    Feature,
    Fee,
    Neighborhood,
    Owner,
    Property,
    PropertyExporter,
    PropertyFee,
    PropertyHistory,
    PropertyPhoto,
    PropertyPrice,
    PropertyType,
    State,
)
from core.services.photos import (
    delete_photo,
    replace_thumbnail,
    resize_upload,
    thumbnail_name,
)


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ["id", "name", "code"]
        read_only_fields = ("id",)


class StateSerializer(serializers.ModelSerializer):
    class Meta:
        model = State
        fields = ["id", "country", "name", "abbreviation"]
        read_only_fields = ("id",)


class CitySerializer(serializers.ModelSerializer):
    class Meta:
        model = City
        fields = ["id", "state", "name", "ibge_code"]
        read_only_fields = ("id",)


class NeighborhoodSerializer(serializers.ModelSerializer):
    # Nomes prontos para a listagem de bairros, que mostra a cidade junto do nome.
    city_name = serializers.CharField(source="city.name", read_only=True)
    state_abbreviation = serializers.CharField(source="city.state.abbreviation", read_only=True)

    class Meta:
        model = Neighborhood
        fields = ["id", "city", "name", "city_name", "state_abbreviation"]
        read_only_fields = ("id", "city_name", "state_abbreviation")

    def validate_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError("Informe o nome do bairro.")

        return value

    def validate(self, attrs):
        city = attrs.get("city", getattr(self.instance, "city", None))
        name = attrs.get("name", getattr(self.instance, "name", None))

        # O banco tem unique (city, name); validar aqui devolve 400 em vez de erro interno.
        duplicates = Neighborhood.objects.filter(city=city, name__iexact=name)

        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        if duplicates.exists():
            raise serializers.ValidationError(
                {"name": "Já existe um bairro com este nome nesta cidade."}
            )

        return attrs


class PropertyTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyType
        fields = ["id", "name"]
        read_only_fields = ("id",)


class CondominiumSerializer(serializers.ModelSerializer):
    # Nomes prontos para a listagem, que mostra o bairro junto do condomínio.
    neighborhood_name = serializers.CharField(
        source="neighborhood.name", read_only=True, allow_null=True
    )
    city_name = serializers.CharField(
        source="neighborhood.city.name", read_only=True, allow_null=True
    )
    # Caminho até o bairro: a tela de edição precisa dele para remontar os selects.
    city_id = serializers.UUIDField(source="neighborhood.city_id", read_only=True, allow_null=True)
    state_id = serializers.UUIDField(
        source="neighborhood.city.state_id", read_only=True, allow_null=True
    )
    state_name = serializers.CharField(
        source="neighborhood.city.state.name", read_only=True, allow_null=True
    )
    country_id = serializers.UUIDField(
        source="neighborhood.city.state.country_id", read_only=True, allow_null=True
    )
    country_name = serializers.CharField(
        source="neighborhood.city.state.country.name", read_only=True, allow_null=True
    )

    class Meta:
        model = Condominium
        fields = [
            "id",
            "name",
            "description",
            "address",
            "neighborhood",
            "neighborhood_name",
            "city_name",
            "city_id",
            "state_id",
            "state_name",
            "country_id",
            "country_name",
            "features",
        ]
        read_only_fields = (
            "id",
            "neighborhood_name",
            "city_name",
            "city_id",
            "state_id",
            "state_name",
            "country_id",
            "country_name",
        )

    def validate_features(self, value):
        # A infraestrutura do imóvel não aparece na tela do condomínio e também não é aceita aqui.
        if any(feature.type != Feature.Type.CONDOMINIUM for feature in value):
            raise serializers.ValidationError(
                "Selecione apenas infraestruturas de condomínio."
            )

        return value


class AgencyContactSerializer(serializers.ModelSerializer):
    """Base de captador e proprietário: mesmos campos e nome único dentro da imobiliária."""

    class Meta:
        fields = ["id", "name", "email", "phone"]
        read_only_fields = ("id",)

    def validate_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError("Informe o nome.")

        # O banco tem unique (agency, name); validar aqui devolve 400 em vez de erro interno.
        duplicates = self.Meta.model.objects.filter(
            agency_id=self.context["request"].user.agency_id,
            name__iexact=value,
        )

        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        if duplicates.exists():
            raise serializers.ValidationError("Já existe um cadastro com este nome.")

        return value


class BrokerSerializer(AgencyContactSerializer):
    class Meta(AgencyContactSerializer.Meta):
        model = Broker


class OwnerSerializer(AgencyContactSerializer):
    """Proprietário: além do contato, guarda a ficha que a listagem de imóveis imprime."""

    neighborhood_name = serializers.CharField(
        source="neighborhood.name", read_only=True, allow_null=True
    )
    city_name = serializers.CharField(
        source="neighborhood.city.name", read_only=True, allow_null=True
    )
    # Caminho até o bairro: a tela de edição precisa dele para remontar os selects.
    city_id = serializers.UUIDField(source="neighborhood.city_id", read_only=True, allow_null=True)
    state_id = serializers.UUIDField(
        source="neighborhood.city.state_id", read_only=True, allow_null=True
    )
    state_name = serializers.CharField(
        source="neighborhood.city.state.name", read_only=True, allow_null=True
    )
    country_id = serializers.UUIDField(
        source="neighborhood.city.state.country_id", read_only=True, allow_null=True
    )
    country_name = serializers.CharField(
        source="neighborhood.city.state.country.name", read_only=True, allow_null=True
    )

    class Meta(AgencyContactSerializer.Meta):
        model = Owner
        fields = [
            "id",
            "name",
            "spouse",
            "email",
            "phone",
            "mobile",
            "business_phone",
            "document",
            "birth_date",
            "address",
            "number",
            "complement",
            "zip_code",
            "neighborhood",
            "neighborhood_name",
            "city_id",
            "city_name",
            "state_id",
            "state_name",
            "country_id",
            "country_name",
            "notes",
            "created_at",
        ]
        read_only_fields = ("id", "created_at")

    def validate_neighborhood(self, value):
        # Bairro é catálogo global, mas o proprietário é da imobiliária: nada a checar por agência.
        return value


class PropertyHistorySerializer(serializers.ModelSerializer):
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = PropertyHistory
        fields = ["id", "action", "action_label", "author_name", "notes", "changes", "created_at"]
        read_only_fields = fields


class ClientSerializer(serializers.ModelSerializer):
    # Nomes prontos para a listagem, que mostra a cidade do cliente.
    neighborhood_name = serializers.CharField(
        source="neighborhood.name", read_only=True, allow_null=True
    )
    city_name = serializers.CharField(
        source="neighborhood.city.name", read_only=True, allow_null=True
    )
    # Caminho até o bairro: a tela de edição precisa dele para remontar os selects.
    city_id = serializers.UUIDField(source="neighborhood.city_id", read_only=True, allow_null=True)
    state_id = serializers.UUIDField(
        source="neighborhood.city.state_id", read_only=True, allow_null=True
    )
    state_name = serializers.CharField(
        source="neighborhood.city.state.name", read_only=True, allow_null=True
    )
    country_id = serializers.UUIDField(
        source="neighborhood.city.state.country_id", read_only=True, allow_null=True
    )
    country_name = serializers.CharField(
        source="neighborhood.city.state.country.name", read_only=True, allow_null=True
    )

    class Meta:
        model = Client
        fields = [
            "id",
            "code",
            "name",
            "email",
            "phone",
            "document",
            "type",
            "birth_date",
            "occupation",
            "address",
            "number",
            "complement",
            "zip_code",
            "neighborhood",
            "neighborhood_name",
            "city_name",
            "city_id",
            "state_id",
            "state_name",
            "country_id",
            "country_name",
            "notes",
            "is_active",
        ]
        read_only_fields = (
            "id",
            "neighborhood_name",
            "city_name",
            "city_id",
            "state_id",
            "state_name",
            "country_id",
            "country_name",
        )

    def validate_name(self, value):
        # Diferente de captador e proprietário, a base de clientes aceita nomes repetidos.
        value = value.strip()

        if not value:
            raise serializers.ValidationError("Informe o nome.")

        return value

    def validate_code(self, value):
        value = value.strip()

        if not value:
            return value

        # O banco tem unique (agency, code); validar aqui devolve 400 em vez de erro interno.
        duplicates = Client.objects.filter(
            agency_id=self.context["request"].user.agency_id,
            code__iexact=value,
        )

        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        if duplicates.exists():
            raise serializers.ValidationError("Já existe um cliente com este código.")

        return value


class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = ["id", "name", "type"]
        read_only_fields = ("id",)


class FeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fee
        fields = ["id", "name"]
        read_only_fields = ("id",)


class ExporterPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExporterPlan
        fields = ["id", "name", "position"]
        read_only_fields = ("id",)


class ExporterSerializer(serializers.ModelSerializer):
    plans = ExporterPlanSerializer(many=True, read_only=True)

    class Meta:
        model = Exporter
        fields = ["id", "name", "slug", "is_active", "plans"]
        read_only_fields = ("id", "plans")

    def validate(self, attrs):
        name = attrs.get("name", getattr(self.instance, "name", ""))
        # O model gera o slug a partir do nome só quando ele chega vazio.
        slug = attrs.get("slug") or getattr(self.instance, "slug", "") or slugify(name)

        duplicates = Exporter.objects.filter(slug=slug)

        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        # O slug é único no banco; validar aqui devolve 400 em vez de erro interno.
        if duplicates.exists():
            raise serializers.ValidationError(
                {"slug": "Já existe um portal com este identificador."}
            )

        return attrs


class AgencyExporterPlanSerializer(serializers.ModelSerializer):
    # Nome e ordem prontos para a tela, sem consultar o catálogo do portal.
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan_position = serializers.IntegerField(source="plan.position", read_only=True)
    used = serializers.SerializerMethodField()

    class Meta:
        model = AgencyExporterPlan
        fields = ["plan", "plan_name", "plan_position", "used", "limit"]
        read_only_fields = ("plan_name", "plan_position", "used")

    def get_used(self, obj) -> int:
        # Vem da anotação do queryset; na resposta de gravação o registro ainda não a tem.
        return getattr(obj, "used", 0)


class AgencyExporterSerializer(serializers.ModelSerializer):
    plans = AgencyExporterPlanSerializer(many=True, required=False)
    # Nome do portal pronto para a listagem e para as mensagens de exclusão.
    name = serializers.CharField(source="exporter.name", read_only=True)
    exported = serializers.SerializerMethodField()

    class Meta:
        model = AgencyExporter
        fields = ["id", "exporter", "name", "exported", "plans", "created_at"]
        read_only_fields = ("id", "name", "exported", "created_at")

    def get_exported(self, obj) -> int:
        # Vem da anotação do queryset; na resposta de gravação o registro ainda não a tem.
        return getattr(obj, "exported", 0)

    def validate_exporter(self, value):
        if value.deleted_at is not None or not value.is_active:
            raise serializers.ValidationError("O portal informado não está disponível.")

        return value

    def validate(self, attrs):
        exporter = attrs.get("exporter", getattr(self.instance, "exporter", None))
        plans = attrs.get("plans")

        if plans:
            plan_ids = [item["plan"].id for item in plans]

            if len(set(plan_ids)) != len(plan_ids):
                raise serializers.ValidationError({"plans": "A lista tem planos repetidos."})

            if any(item["plan"].exporter_id != exporter.id for item in plans):
                raise serializers.ValidationError(
                    {"plans": "O plano informado não pertence a este portal."}
                )

        # O banco tem unique (agency, exporter); validar aqui devolve 400 em vez de erro interno.
        duplicates = AgencyExporter.objects.filter(
            agency_id=self.context["request"].user.agency_id, exporter=exporter
        )

        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        if duplicates.exists():
            raise serializers.ValidationError({"exporter": "Este portal já está configurado."})

        return attrs

    def create(self, validated_data):
        plans = validated_data.pop("plans", [])
        instance = super().create(validated_data)
        self._save_plans(instance, plans)

        return instance

    def update(self, instance, validated_data):
        plans = validated_data.pop("plans", None)
        instance = super().update(instance, validated_data)

        if plans is not None:
            instance.plans.all().delete()
            self._save_plans(instance, plans)

        return instance

    def _save_plans(self, instance, plans):
        # Os planos são fixos do portal: a configuração espelha todos, e o não informado fica com zero.
        limits = {item["plan"].id: item.get("limit", 0) for item in plans}

        AgencyExporterPlan.objects.bulk_create(
            [
                AgencyExporterPlan(
                    agency_exporter=instance, plan=plan, limit=limits.get(plan.id, 0)
                )
                for plan in instance.exporter.plans.all()
            ]
        )


class PropertyExporterSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyExporter
        fields = ["exporter", "plan"]

    def validate(self, attrs):
        if attrs["plan"].exporter_id != attrs["exporter"].id:
            raise serializers.ValidationError(
                {"plan": "O plano informado não pertence a este exportador."}
            )

        agency_id = self.context["request"].user.agency_id
        rule = AgencyExporterPlan.objects.filter(
            agency_exporter__agency_id=agency_id,
            agency_exporter__exporter_id=attrs["exporter"].id,
            plan=attrs["plan"],
        ).first()

        if rule is None or rule.limit == 0:
            raise serializers.ValidationError(
                {"plan": "Configure este portal em Integrações antes de exportar imóveis."}
            )

        used = PropertyExporter.objects.filter(
            plan=attrs["plan"],
            property__agency_id=agency_id,
            property__deleted_at__isnull=True,
        )

        # Na edição o imóvel não conta contra o próprio limite: as linhas dele são regravadas.
        current_property = self.root.instance if self.root is not None else None

        if current_property is not None:
            used = used.exclude(property=current_property)

        if used.count() >= rule.limit:
            raise serializers.ValidationError(
                {
                    "plan": (
                        f"O plano {attrs['plan'].name} já atingiu o limite de "
                        f"{rule.limit} imóveis neste portal."
                    )
                }
            )

        return attrs


class PropertyPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyPrice
        fields = ["purpose", "amount", "notes"]


class PropertyFeeSerializer(serializers.ModelSerializer):
    # Nome pronto para a listagem, que mostra as taxas sem consultar o catálogo.
    fee_name = serializers.CharField(source="fee.name", read_only=True)

    class Meta:
        model = PropertyFee
        fields = ["fee", "fee_name", "amount", "notes"]
        read_only_fields = ("fee_name",)


class PhotoSerializer(serializers.ModelSerializer):
    """Base das galerias: mesma validação de arquivo, miniatura e limite nos dois cadastros."""

    # Como o dono da galeria aparece nas mensagens de erro.
    parent_label = ""

    thumbnail = serializers.SerializerMethodField()

    class Meta:
        fields = [
            "id",
            "image",
            "thumbnail",
            "is_main",
            "position",
            "file_size",
            "created_at",
        ]
        read_only_fields = ("id", "file_size", "created_at")

    def get_thumbnail(self, instance):
        # A mini existe só para a foto principal da galeria.
        if not instance.is_main or not instance.image:
            return None

        url = instance.image.storage.url(thumbnail_name(instance.image.name))
        request = self.context.get("request")

        return request.build_absolute_uri(url) if request else url

    def validate_image(self, value):
        return validate_image_upload(value)

    def validate(self, attrs):
        # O limite vale só para foto nova; trocar miniatura ou posição não cria arquivo.
        if self.instance is None:
            limit = settings.PROPERTY_PHOTO_MAX_PER_PROPERTY

            if self._current_photos(attrs[self.Meta.model.parent_field]).count() >= limit:
                raise serializers.ValidationError(
                    {"image": f"O {self.parent_label} já atingiu o limite de {limit} fotos."}
                )

        return attrs

    def create(self, validated_data):
        parent = validated_data[self.Meta.model.parent_field]
        validated_data["image"] = resize_upload(validated_data["image"])

        # A primeira foto da galeria já entra como miniatura.
        if not self._current_photos(parent).exists():
            validated_data["is_main"] = True

        previous_main = self._clear_main_photo(parent) if validated_data.get("is_main") else None
        instance = super().create(validated_data)

        if instance.is_main:
            replace_thumbnail(instance, previous_main)

        return instance

    def update(self, instance, validated_data):
        becoming_main = validated_data.get("is_main") and not instance.is_main
        previous_main = (
            self._clear_main_photo(instance.parent, exclude=instance)
            if validated_data.get("is_main")
            else None
        )
        instance = super().update(instance, validated_data)

        if becoming_main:
            replace_thumbnail(instance, previous_main)

        return instance

    def _validate_parent(self, value):
        # Impede anexar fotos a um cadastro de outra imobiliária passando o id direto no payload.
        if value.agency_id != self.context["request"].user.agency_id:
            raise serializers.ValidationError(f"O {self.parent_label} informado não existe.")

        return value

    def _current_photos(self, parent):
        return parent.photos.filter(deleted_at__isnull=True)

    def _clear_main_photo(self, parent, exclude=None):
        # Só uma foto pode ser a principal por galeria.
        queryset = self._current_photos(parent).filter(is_main=True)

        if exclude is not None:
            queryset = queryset.exclude(pk=exclude.pk)

        previous_main = queryset.first()
        queryset.update(is_main=False)

        return previous_main


class PropertyPhotoSerializer(PhotoSerializer):
    parent_label = "imóvel"

    class Meta(PhotoSerializer.Meta):
        model = PropertyPhoto
        fields = PhotoSerializer.Meta.fields + ["property"]

    def validate_property(self, value):
        return self._validate_parent(value)


class CondominiumPhotoSerializer(PhotoSerializer):
    parent_label = "condomínio"

    class Meta(PhotoSerializer.Meta):
        model = CondominiumPhoto
        fields = PhotoSerializer.Meta.fields + ["condominium"]

    def validate_condominium(self, value):
        return self._validate_parent(value)


class PhotoBulkDeleteSerializer(serializers.Serializer):
    """Base do apagar-todas: remove as fotos ativas do imóvel ou do condomínio informado."""

    parent_field = ""
    parent_label = ""

    def _validate_parent(self, value):
        if value.agency_id != self.context["request"].user.agency_id:
            raise serializers.ValidationError(f"O {self.parent_label} informado não existe.")

        return value

    def save(self, **kwargs):
        parent = self.validated_data[self.parent_field]
        photos = list(parent.photos.filter(deleted_at__isnull=True))

        for photo in photos:
            delete_photo(photo, promote=False)

        return photos


class PropertyPhotoBulkDeleteSerializer(PhotoBulkDeleteSerializer):
    parent_field = "property"
    parent_label = "imóvel"

    property = serializers.PrimaryKeyRelatedField(queryset=Property.objects.all())

    def validate_property(self, value):
        return self._validate_parent(value)


class CondominiumPhotoBulkDeleteSerializer(PhotoBulkDeleteSerializer):
    parent_field = "condominium"
    parent_label = "condomínio"

    condominium = serializers.PrimaryKeyRelatedField(queryset=Condominium.objects.all())

    def validate_condominium(self, value):
        return self._validate_parent(value)


class PhotoReorderSerializer(serializers.Serializer):
    """Base da reordenação: a nova posição de cada foto é o lugar dela na lista enviada."""

    photo_model = None
    parent_label = ""

    photos = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=200
    )

    def validate_photos(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("A ordem enviada tem fotos repetidas.")

        photos = self._scoped_photos(value)

        # Id inexistente ou de outra imobiliária não pode passar: a busca é sempre escopada.
        if len(photos) != len(value):
            raise serializers.ValidationError("Alguma foto informada não existe.")

        parent_field = self.photo_model.parent_field

        if len({getattr(photo, f"{parent_field}_id") for photo in photos}) != 1:
            raise serializers.ValidationError(f"Envie as fotos de um único {self.parent_label}.")

        return value

    def _scoped_photos(self, photo_ids):
        user = self.context["request"].user
        parent_field = self.photo_model.parent_field

        return list(
            self.photo_model.objects.filter(
                **{
                    "id__in": photo_ids,
                    f"{parent_field}__agency_id": user.agency_id,
                    f"{parent_field}__deleted_at__isnull": True,
                    "deleted_at__isnull": True,
                }
            )
        )

    def save(self, **kwargs):
        photo_ids = [str(photo_id) for photo_id in self.validated_data["photos"]]
        photos_by_id = {str(photo.id): photo for photo in self._scoped_photos(photo_ids)}
        ordered = []

        for position, photo_id in enumerate(photo_ids, start=1):
            photo = photos_by_id[photo_id]
            photo.position = position
            ordered.append(photo)

        self.photo_model.objects.bulk_update(ordered, ["position"])

        return ordered


class PropertyPhotoReorderSerializer(PhotoReorderSerializer):
    photo_model = PropertyPhoto
    parent_label = "imóvel"


class CondominiumPhotoReorderSerializer(PhotoReorderSerializer):
    photo_model = CondominiumPhoto
    parent_label = "condomínio"


class PropertySerializer(serializers.ModelSerializer):
    # Declarado à mão porque o cadastro passou a informar o código; sem ele, a numeração é automática.
    code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    # O nome não é pedido na tela: o model monta a partir do tipo e do bairro.
    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    photos = PropertyPhotoSerializer(many=True, read_only=True)
    prices = PropertyPriceSerializer(many=True, required=False)
    fees = PropertyFeeSerializer(many=True, required=False)
    exporters = PropertyExporterSerializer(many=True, required=False)

    # Nomes prontos para a listagem, evitando uma requisição por relacionamento no frontend.
    type_name = serializers.CharField(source="type.name", read_only=True, allow_null=True)
    condominium_name = serializers.CharField(source="condominium.name", read_only=True, allow_null=True)
    neighborhood_name = serializers.CharField(source="neighborhood.name", read_only=True, allow_null=True)
    city_name = serializers.CharField(source="neighborhood.city.name", read_only=True, allow_null=True)
    state_abbreviation = serializers.CharField(
        source="neighborhood.city.state.abbreviation", read_only=True, allow_null=True
    )
    # Ids do caminho até o bairro: a tela de edição precisa deles para remontar os selects.
    city_id = serializers.UUIDField(source="neighborhood.city_id", read_only=True, allow_null=True)
    state_id = serializers.UUIDField(
        source="neighborhood.city.state_id", read_only=True, allow_null=True
    )
    state_name = serializers.CharField(
        source="neighborhood.city.state.name", read_only=True, allow_null=True
    )
    country_id = serializers.UUIDField(
        source="neighborhood.city.state.country_id", read_only=True, allow_null=True
    )
    broker_name = serializers.CharField(source="broker.name", read_only=True, allow_null=True)
    owner_display_name = serializers.CharField(source="owner.name", read_only=True, allow_null=True)
    # A ficha do proprietário sai junto: quem só tem Imóveis não alcança /owners/.
    owner_data = OwnerSerializer(source="owner", read_only=True)

    class Meta:
        model = Property
        fields = [
            "id",
            "code",
            "type",
            "type_name",
            "condominium",
            "condominium_name",
            "neighborhood",
            "neighborhood_name",
            "city_name",
            "state_abbreviation",
            "city_id",
            "state_id",
            "state_name",
            "country_id",
            "broker",
            "broker_name",
            "owner",
            "owner_display_name",
            "owner_data",
            "features",
            "name",
            "description",
            "address",
            "number",
            "complement",
            "zip_code",
            "owner_name",
            "local_contact",
            "contact_phone",
            "area",
            "built_area",
            "bedrooms",
            "suites",
            "bathrooms",
            "living_rooms",
            "parking_spaces",
            "guests",
            "video_url",
            "maps_url",
            "visit_notes",
            "document_notes",
            "is_active",
            "featured",
            "exclusive",
            "reserved",
            "under_construction",
            "opportunity",
            "has_leasehold",
            "on_site",
            "show_prices",
            "accepts_trade",
            "trade_conditions",
            "views_count",
            "photos",
            "prices",
            "fees",
            "exporters",
            "created_at",
            "updated_at",
        ]
        # A imobiliária vem sempre do usuário autenticado, nunca do payload.
        read_only_fields = (
            "id",
            "type_name",
            "condominium_name",
            "neighborhood_name",
            "city_name",
            "state_abbreviation",
            "city_id",
            "state_id",
            "state_name",
            "country_id",
            "broker_name",
            "owner_display_name",
            "views_count",
            "created_at",
            "updated_at",
        )

    def validate_code(self, value):
        value = value.strip()

        if not value:
            return value

        # O unique é (agency, code) e vale também para imóvel excluído, que mantém o código.
        duplicates = Property.objects.filter(
            agency_id=self.context["request"].user.agency_id, code__iexact=value
        )

        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        if duplicates.exists():
            raise serializers.ValidationError("Já existe um imóvel com este código.")

        return value

    def validate_features(self, value):
        # A infraestrutura do condomínio não aparece na tela do imóvel e também não é aceita aqui.
        if any(feature.type != Feature.Type.PROPERTY for feature in value):
            raise serializers.ValidationError("Selecione apenas infraestruturas de imóvel.")

        return value

    def validate_condominium(self, value):
        # Impede vincular um condomínio de outra imobiliária passando o id direto no payload.
        return self._validate_agency_scope(value, "O condomínio informado não existe.")

    def validate_broker(self, value):
        return self._validate_agency_scope(value, "O captador informado não existe.")

    def validate_owner(self, value):
        return self._validate_agency_scope(value, "O proprietário informado não existe.")

    def _validate_agency_scope(self, value, message):
        if value is not None and value.agency_id != self.context["request"].user.agency_id:
            raise serializers.ValidationError(message)

        return value

    def create(self, validated_data):
        prices = validated_data.pop("prices", [])
        fees = validated_data.pop("fees", [])
        exporters = validated_data.pop("exporters", [])

        instance = super().create(validated_data)
        self._save_prices(instance, prices)
        self._save_fees(instance, fees)
        self._save_exporters(instance, exporters)

        return instance

    def update(self, instance, validated_data):
        prices = validated_data.pop("prices", None)
        fees = validated_data.pop("fees", None)
        exporters = validated_data.pop("exporters", None)

        instance = super().update(instance, validated_data)

        if prices is not None:
            instance.prices.all().delete()
            self._save_prices(instance, prices)

        if fees is not None:
            instance.fees.all().delete()
            self._save_fees(instance, fees)

        if exporters is not None:
            instance.exporters.all().delete()
            self._save_exporters(instance, exporters)

        return instance

    def _save_prices(self, instance, prices):
        PropertyPrice.objects.bulk_create(
            [PropertyPrice(property=instance, **price) for price in prices]
        )

    def _save_fees(self, instance, fees):
        PropertyFee.objects.bulk_create(
            [PropertyFee(property=instance, **fee) for fee in fees]
        )

    def _save_exporters(self, instance, exporters):
        PropertyExporter.objects.bulk_create(
            [PropertyExporter(property=instance, **exporter) for exporter in exporters]
        )
