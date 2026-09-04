from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.classes.envelope import error_response, serializer_errors, success_response
from core.classes.permission_resource import ResourcePermission
from core.classes.permission_type_user import AllPermissionClass, raise_permission_denied
from core.models import Lead, User
from core.resources import AccessLevel, requires_level
from core.serializers.queue import (
    AssignSerializer,
    CloseSerializer,
    DeclineSerializer,
    EnqueueSerializer,
    MoveSerializer,
    NoteSerializer,
    PresenceSerializer,
    QueueBrokerSerializer,
    QueueLeadSerializer,
    QueueSettingsSerializer,
    ReturnSerializer,
)
from core.services import queue as queue_service

UUID = r'[0-9a-fA-F-]{36}'
LEAD_PATH = rf'leads/(?P<lead_id>{UUID})'
BROKER_PATH = rf'brokers/(?P<user_id>{UUID})'


class QueueViewSet(viewsets.GenericViewSet):
    """Fila de atendimento: a leitura devolve o estado inteiro e cada botão da tela é uma action.

    O corretor (type BROKER) só mexe no que está com ele: aceitar, recusar, registrar ação,
    encerrar e a própria presença. O resto é do gestor.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, AllPermissionClass, ResourcePermission]
    resource = 'fila'

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)

        if request.user.agency_id is None:
            raise_permission_denied('Seu usuário não está vinculado a uma imobiliária.')

        self.agency_id = request.user.agency_id

    def list(self, request):
        now = timezone.now()
        # O relógio da fila roda a cada leitura: a tela consulta de poucos em poucos segundos.
        queue_service.tick(self.agency_id, now)

        data = {
            'now': now,
            'viewer': {'id': str(request.user.id), 'is_manager': self._is_manager(request.user)},
            'settings': QueueSettingsSerializer(queue_service.settings_for(self.agency_id)).data,
            'brokers': QueueBrokerSerializer(queue_service.brokers_for(self.agency_id), many=True).data,
            'leads': QueueLeadSerializer(self._visible_leads(request.user, now), many=True).data,
        }
        return success_response(data)

    @action(detail=False, methods=['put', 'patch'], url_path='settings')
    @requires_level(AccessLevel.WRITE)
    def queue_settings(self, request):
        self._require_manager(request.user)
        instance = queue_service.settings_for(self.agency_id)
        serializer = QueueSettingsSerializer(instance, data=request.data, partial=request.method == 'PATCH')

        if not serializer.is_valid():
            return error_response('Dados inválidos.', serializer_errors(serializer))

        serializer.save()
        return success_response(serializer.data, 'Configuração da fila salva.')

    @action(detail=False, methods=['post'], url_path='leads')
    @requires_level(AccessLevel.WRITE)
    def enqueue(self, request):
        self._require_manager(request.user)
        serializer = self._validate(EnqueueSerializer, request)
        if serializer.errors:
            return self._invalid(serializer)

        lead = self._lead(serializer.validated_data['lead'])
        return self._run(lambda: queue_service.enqueue(lead), 'Lead lançado na fila.', status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path=f'{LEAD_PATH}/accept')
    @requires_level(AccessLevel.WRITE)
    def accept(self, request, lead_id=None):
        lead = self._own_lead(request.user, lead_id)
        return self._run(lambda: queue_service.accept(lead), 'Atendimento aceito.')

    @action(detail=False, methods=['post'], url_path=f'{LEAD_PATH}/decline')
    @requires_level(AccessLevel.WRITE)
    def decline(self, request, lead_id=None):
        lead = self._own_lead(request.user, lead_id)
        serializer = self._validate(DeclineSerializer, request)
        if serializer.errors:
            return self._invalid(serializer)

        reason = serializer.validated_data.get('reason', '')
        return self._run(lambda: queue_service.decline(lead, reason), 'Lead passado adiante.')

    @action(detail=False, methods=['post'], url_path=f'{LEAD_PATH}/notes')
    @requires_level(AccessLevel.WRITE)
    def note(self, request, lead_id=None):
        lead = self._own_lead(request.user, lead_id)
        serializer = self._validate(NoteSerializer, request)
        if serializer.errors:
            return self._invalid(serializer)

        queue_service.add_note(lead, request.user, serializer.validated_data['text'])
        return self._lead_response(lead.id, 'Ação registrada.', status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path=f'{LEAD_PATH}/close')
    @requires_level(AccessLevel.WRITE)
    def close(self, request, lead_id=None):
        lead = self._own_lead(request.user, lead_id)
        serializer = self._validate(CloseSerializer, request)
        if serializer.errors:
            return self._invalid(serializer)

        data = serializer.validated_data
        return self._run(
            lambda: queue_service.close(lead, data['outcome'], data.get('detail', '')),
            'Atendimento encerrado.',
        )

    @action(detail=False, methods=['post'], url_path=f'{LEAD_PATH}/assign')
    @requires_level(AccessLevel.WRITE)
    def assign(self, request, lead_id=None):
        self._require_manager(request.user)
        lead = self._lead(lead_id)
        serializer = self._validate(AssignSerializer, request)
        if serializer.errors:
            return self._invalid(serializer)

        broker = self._broker(serializer.validated_data['user'])
        return self._run(lambda: queue_service.assign(lead, broker), 'Lead atribuído.')

    @action(detail=False, methods=['post'], url_path=f'{LEAD_PATH}/return')
    @requires_level(AccessLevel.WRITE)
    def return_to_queue(self, request, lead_id=None):
        self._require_manager(request.user)
        lead = self._lead(lead_id)
        serializer = self._validate(ReturnSerializer, request)
        if serializer.errors:
            return self._invalid(serializer)

        reason = serializer.validated_data.get('reason', '')
        return self._run(lambda: queue_service.return_to_queue(lead, reason), 'Lead devolvido à fila.')

    @action(detail=False, methods=['post'], url_path=f'{BROKER_PATH}/presence')
    @requires_level(AccessLevel.WRITE)
    def presence(self, request, user_id=None):
        broker = self._broker(user_id)

        # O corretor pausa e volta sozinho; mexer na presença dos outros é do gestor.
        if not self._is_manager(request.user) and broker.id != request.user.id:
            raise_permission_denied('Você só pode alterar a sua própria presença na fila.')

        serializer = self._validate(PresenceSerializer, request)
        if serializer.errors:
            return self._invalid(serializer)

        data = serializer.validated_data
        queue_service.set_presence(broker, data['presence'], data.get('pause_reason', ''))
        return success_response(QueueBrokerSerializer(broker).data, 'Presença atualizada.')

    @action(detail=False, methods=['post'], url_path=f'{BROKER_PATH}/move')
    @requires_level(AccessLevel.WRITE)
    def move(self, request, user_id=None):
        self._require_manager(request.user)
        broker = self._broker(user_id)
        serializer = self._validate(MoveSerializer, request)
        if serializer.errors:
            return self._invalid(serializer)

        queue_service.move_broker(broker, serializer.validated_data['direction'])
        return success_response(
            QueueBrokerSerializer(queue_service.brokers_for(self.agency_id), many=True).data,
            'Ordem da roleta atualizada.',
        )

    @action(detail=False, methods=['post'], url_path=f'{BROKER_PATH}/toggle')
    @requires_level(AccessLevel.WRITE)
    def toggle(self, request, user_id=None):
        self._require_manager(request.user)
        broker = queue_service.toggle_queue(self._broker(user_id))
        return success_response(QueueBrokerSerializer(broker).data, 'Roleta atualizada.')

    def _is_manager(self, user):
        return user.type != User.Type.BROKER

    def _require_manager(self, user):
        if not self._is_manager(user):
            raise_permission_denied('Só o gestor pode fazer isso na fila.')

    def _leads(self):
        return (
            queue_service.queue_leads(self.agency_id)
            .select_related('assigned_to')
            .prefetch_related('interactions')
        )

    def _lead(self, lead_id):
        return get_object_or_404(self._leads(), pk=lead_id)

    def _own_lead(self, user, lead_id):
        lead = self._lead(lead_id)

        if not self._is_manager(user) and lead.assigned_to_id != user.id:
            raise_permission_denied('Este lead não está com você.')

        return lead

    def _broker(self, user_id):
        return get_object_or_404(
            User.objects.filter(
                agency_id=self.agency_id,
                type=User.Type.BROKER,
                is_active=True,
                deleted_at__isnull=True,
            ),
            pk=user_id,
        )

    def _visible_leads(self, user, now):
        """Abertos mais os encerrados hoje, que ainda contam nos indicadores do dia."""
        start_of_day = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        leads = self._leads().filter(
            Q(queue_status__in=queue_service.OPEN_STATUSES)
            | Q(queue_status=Lead.QueueStatus.CLOSED, queue_closed_at__gte=start_of_day)
        )

        if not self._is_manager(user):
            leads = leads.filter(assigned_to=user)

        return leads.order_by('-created_at')

    def _validate(self, serializer_class, request):
        serializer = serializer_class(data=request.data)
        serializer.is_valid()
        return serializer

    def _invalid(self, serializer):
        return error_response('Dados inválidos.', serializer_errors(serializer))

    def _run(self, operation, message, status_code=status.HTTP_200_OK):
        try:
            lead = operation()
        except queue_service.QueueError as exc:
            return error_response(str(exc))

        return self._lead_response(lead.id, message, status_code)

    def _lead_response(self, lead_id, message, status_code=status.HTTP_200_OK):
        return success_response(QueueLeadSerializer(self._lead(lead_id)).data, message, status_code)
