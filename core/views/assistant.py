from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.classes.base_viewset import BaseViewSet
from core.classes.permission_type_user import AllPermissionClass, raise_permission_denied
from core.models import AssistantConversation
from core.resources import AccessLevel
from core.serializers import (
    AssistantChatSerializer,
    AssistantConversationDetailSerializer,
    AssistantConversationSerializer,
    AssistantPropertySearchSerializer,
)
from core.services.assistant import AssistantError, ask, extract_property_search


class AssistantConversationViewSet(BaseViewSet):
    """Histórico de conversas do Theo; cada usuário só enxerga as próprias.

    Sem `resource` de propósito: o Theo não é uma tela do menu, e a permissão por área
    é aplicada dentro de cada ferramenta de consulta do assistente.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, AllPermissionClass]
    serializer_class = AssistantConversationSerializer
    http_method_names = ['get', 'delete', 'head', 'options']

    def get_queryset(self):
        return AssistantConversation.objects.filter(
            agency_id=self.request.user.agency_id,
            user=self.request.user,
            deleted_at__isnull=True,
        ).order_by('-updated_at')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return AssistantConversationDetailSerializer

        return AssistantConversationSerializer


class AssistantChatView(APIView):
    """Recebe a pergunta do usuário e devolve a resposta do Theo."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, AllPermissionClass]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'assistant'

    def post(self, request):
        serializer = AssistantChatSerializer(data=request.data)

        if not serializer.is_valid():
            return self._error(
                'Dados inválidos.',
                status.HTTP_400_BAD_REQUEST,
                errors=[
                    {'field': field, 'message': str(messages[0])}
                    for field, messages in serializer.errors.items()
                ],
            )

        if not request.user.agency_id:
            return self._error(
                'Seu usuário não está vinculado a uma imobiliária.',
                status.HTTP_400_BAD_REQUEST,
            )

        conversation = None
        conversation_id = serializer.validated_data.get('conversation')

        if conversation_id:
            conversation = AssistantConversation.objects.filter(
                id=conversation_id, user=request.user, deleted_at__isnull=True
            ).first()

            if conversation is None:
                return self._error('Conversa não encontrada.', status.HTTP_404_NOT_FOUND)

        try:
            conversation, reply = ask(
                user=request.user,
                text=serializer.validated_data['message'],
                conversation=conversation,
            )
        except AssistantError as exc:
            return self._error(str(exc), status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(
            {
                'status': 'success',
                'message': 'Resposta do assistente.',
                'data': {
                    'conversation': {'id': str(conversation.id), 'title': conversation.title},
                    'reply': reply,
                },
                'errors': [],
            },
            status=status.HTTP_200_OK,
        )

    def _error(self, message, http_status, errors=None):
        return Response(
            {'status': 'error', 'message': message, 'data': None, 'errors': errors or []},
            status=http_status,
        )


class AssistantPropertySearchView(APIView):
    """Converte a descrição em linguagem natural nos filtros da listagem de imóveis."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, AllPermissionClass]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'assistant'

    def post(self, request):
        # É uma leitura de imóveis, apesar do POST; a checagem manual evita exigir escrita.
        if not request.user.can('imoveis', AccessLevel.READ):
            raise_permission_denied('Você não tem acesso a Imóveis.')

        serializer = AssistantPropertySearchSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {
                    'status': 'error',
                    'message': 'Dados inválidos.',
                    'data': None,
                    'errors': [
                        {'field': field, 'message': str(messages[0])}
                        for field, messages in serializer.errors.items()
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = extract_property_search(
                user=request.user, text=serializer.validated_data['query']
            )
        except AssistantError as exc:
            return Response(
                {'status': 'error', 'message': str(exc), 'data': None, 'errors': []},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                'status': 'success',
                'message': 'Pesquisa interpretada.',
                'data': result,
                'errors': [],
            },
            status=status.HTTP_200_OK,
        )
