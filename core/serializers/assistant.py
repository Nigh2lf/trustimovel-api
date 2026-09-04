from rest_framework import serializers

from core.models import AssistantConversation, AssistantMessage


class AssistantMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssistantMessage
        fields = ['id', 'role', 'content', 'created_at']
        read_only_fields = fields


class AssistantConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssistantConversation
        fields = ['id', 'title', 'created_at', 'updated_at']
        read_only_fields = fields


class AssistantConversationDetailSerializer(AssistantConversationSerializer):
    messages = AssistantMessageSerializer(many=True, read_only=True)

    class Meta(AssistantConversationSerializer.Meta):
        fields = AssistantConversationSerializer.Meta.fields + ['messages']
        read_only_fields = fields


class AssistantPropertySearchSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=500)

    def validate_query(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError('Descreva o imóvel que procura.')

        return value


class AssistantChatSerializer(serializers.Serializer):
    conversation = serializers.UUIDField(required=False, allow_null=True)
    message = serializers.CharField(max_length=2000)

    def validate_message(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError('Escreva uma pergunta para o Theo.')

        return value
