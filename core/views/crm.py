from datetime import timedelta

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination

from core.classes.permission_type_user import raise_permission_denied
from core.filters import DealFilter, TaskFilter, overdue_tasks_condition
from core.models import Deal, Lead, LeadInteraction, ServiceTicketMessage, ServiceTicket, Task, User
from core.resources import AccessLevel, requires_level
from core.serializers import (
    DealSerializer,
    LeadInteractionSerializer,
    LeadSerializer,
    ServiceTicketMessageSerializer,
    ServiceTicketSerializer,
    TaskSerializer,
)
from core.services import queue as queue_service
from core.views.property import AgencyScopedViewSet


class CrmPagination(PageNumberPagination):
    """Página normal nas listas; o quadro do funil e a agenda pedem páginas maiores e seguem o `next`."""

    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 200


def _author_name(user):
    return user.name or user.email


def _summary_response(view, data):
    return view._response_format(True, status.HTTP_200_OK, data=data)


class LeadViewSet(AgencyScopedViewSet):
    resource = 'leads'
    model = Lead
    serializer_class = LeadSerializer
    pagination_class = CrmPagination
    search_fields = ['code', 'name', 'email', 'phone']
    filterset_fields = ['status', 'source', 'responsible', 'assigned_to', 'queue_status']
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    ordering_fields = (
        'code',
        'name',
        'status',
        'source',
        'interest',
        'responsible__name',
        'assigned_to__name',
        'queue_status',
        'last_contact_at',
        'created_at',
    )
    ordering = ('-created_at',)

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related('responsible', 'assigned_to')
            .prefetch_related('interactions')
        )

    @action(detail=False, methods=['get'], url_path='summary')
    @requires_level(AccessLevel.READ)
    def summary(self, request):
        """Indicadores do topo da tela, contados no servidor com os mesmos filtros da lista."""
        counts = self.filter_queryset(self.get_queryset()).aggregate(
            total=Count('id'),
            **{value.lower(): Count('id', filter=Q(status=value)) for value in Lead.Status.values},
        )

        return _summary_response(self, counts)

    @action(detail=False, methods=['get'], url_path='brokers')
    @requires_level(AccessLevel.READ)
    def brokers(self, request):
        """Corretores (usuários) que podem ficar com um lead, no formato do combobox da tela."""
        search = request.query_params.get('search', '').strip()
        users = User.objects.filter(
            agency_id=request.user.agency_id,
            type=User.Type.BROKER,
            is_active=True,
            deleted_at__isnull=True,
        )

        if search:
            users = users.filter(Q(name__icontains=search) | Q(email__icontains=search))

        results = [
            {'id': str(user.id), 'name': user.name or user.email}
            for user in users.order_by('name', 'email')[:50]
        ]

        return self._response_format(
            True, status.HTTP_200_OK, data={'count': len(results), 'results': results}
        )

    @action(detail=True, methods=['post'], url_path='interactions')
    @requires_level(AccessLevel.WRITE)
    def add_interaction(self, request, pk=None):
        lead = self.get_object()
        serializer = LeadInteractionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Passa pela fila: se o lead aguarda o primeiro contato, esta ação é o primeiro contato.
        interaction = queue_service.add_note(lead, request.user, serializer.validated_data['text'])

        return self._response_format(
            True, status.HTTP_201_CREATED, data=LeadInteractionSerializer(interaction).data
        )

    @action(detail=True, methods=['post'], url_path='convert')
    @requires_level(AccessLevel.WRITE)
    def convert(self, request, pk=None):
        lead = self.get_object()

        # A conversão grava no funil, então exige a permissão de escrita de lá também.
        if not request.user.can('funil', AccessLevel.WRITE):
            raise_permission_denied('Você não tem permissão para criar negócios no Funil de Vendas.')

        if lead.status == Lead.Status.CONVERTED:
            return self._response_format(
                False, status.HTTP_400_BAD_REQUEST, message='Este lead já foi convertido.'
            )

        deal = Deal.objects.create(
            agency_id=lead.agency_id,
            title=f'{lead.get_interest_display()} — {lead.name}',
            client_name=lead.name,
            stage=Deal.Stage.QUALIFICATION,
            probability=10,
            estimated_close=timezone.localdate() + timedelta(days=30),
            responsible=lead.responsible,
            origin=lead.source,
            type=Deal.Type.RENT if lead.interest == Lead.Interest.RENT else Deal.Type.SALE,
            description=lead.observations,
            lead=lead,
        )

        lead.status = Lead.Status.CONVERTED
        lead.last_contact_at = timezone.localdate()
        lead.save(update_fields=['status', 'last_contact_at', 'updated_at'])

        LeadInteraction.objects.create(
            lead=lead,
            author_name=_author_name(request.user),
            text='Convertido em negócio no Funil de Vendas.',
        )

        return self._response_format(
            True, status.HTTP_201_CREATED, data=DealSerializer(deal).data
        )


class ServiceTicketViewSet(AgencyScopedViewSet):
    resource = 'atendimentos'
    model = ServiceTicket
    serializer_class = ServiceTicketSerializer
    pagination_class = CrmPagination
    search_fields = ['protocol', 'client_name', 'subject']
    filterset_fields = ['status', 'priority', 'category', 'responsible']
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    ordering_fields = (
        'protocol',
        'client_name',
        'subject',
        'category',
        'status',
        'priority',
        'responsible__name',
        'created_at',
        'updated_at',
    )
    ordering = ('-created_at',)

    def get_queryset(self):
        return super().get_queryset().select_related('responsible').prefetch_related('messages')

    @action(detail=False, methods=['get'], url_path='summary')
    @requires_level(AccessLevel.READ)
    def summary(self, request):
        open_statuses = [
            ServiceTicket.Status.NEW,
            ServiceTicket.Status.IN_PROGRESS,
            ServiceTicket.Status.AWAITING_RESPONSE,
        ]
        counts = self.filter_queryset(self.get_queryset()).aggregate(
            total=Count('id'),
            open=Count('id', filter=Q(status__in=open_statuses)),
            resolved=Count(
                'id',
                filter=Q(status__in=[ServiceTicket.Status.RESOLVED, ServiceTicket.Status.CLOSED]),
            ),
            urgent=Count(
                'id', filter=Q(status__in=open_statuses, priority=ServiceTicket.Priority.URGENT)
            ),
        )

        return _summary_response(self, counts)

    @action(detail=True, methods=['post'], url_path='messages')
    @requires_level(AccessLevel.WRITE)
    def add_message(self, request, pk=None):
        ticket = self.get_object()
        serializer = ServiceTicketMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        message = serializer.save(ticket=ticket, author_name=_author_name(request.user))

        # O save vazio carimba o updated_at, que a listagem mostra como última atualização.
        ticket.save(update_fields=['updated_at'])

        return self._response_format(
            True, status.HTTP_201_CREATED, data=ServiceTicketMessageSerializer(message).data
        )


class TaskViewSet(AgencyScopedViewSet):
    resource = 'tarefas'
    model = Task
    serializer_class = TaskSerializer
    pagination_class = CrmPagination
    search_fields = ['title', 'description']
    filterset_class = TaskFilter
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    ordering_fields = (
        'title',
        'type',
        'status',
        'priority',
        'responsible__name',
        'due_date',
        'created_at',
    )
    ordering = ('due_date', 'due_time')

    def get_queryset(self):
        return super().get_queryset().select_related('responsible', 'lead', 'deal')

    @action(detail=False, methods=['get'], url_path='summary')
    @requires_level(AccessLevel.READ)
    def summary(self, request):
        counts = self.filter_queryset(self.get_queryset()).aggregate(
            total=Count('id'),
            pending=Count('id', filter=~Q(status=Task.Status.DONE)),
            done=Count('id', filter=Q(status=Task.Status.DONE)),
            overdue=Count('id', filter=overdue_tasks_condition()),
        )

        return _summary_response(self, counts)


class DealViewSet(AgencyScopedViewSet):
    resource = 'funil'
    model = Deal
    serializer_class = DealSerializer
    pagination_class = CrmPagination
    search_fields = ['title', 'client_name', 'property_code']
    filterset_class = DealFilter
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    ordering_fields = (
        'title',
        'client_name',
        'value',
        'stage',
        'probability',
        'responsible__name',
        'estimated_close',
        'closed_at',
        'created_at',
    )
    ordering = ('-created_at',)

    def get_queryset(self):
        return super().get_queryset().select_related('responsible')

    @action(detail=False, methods=['get'], url_path='summary')
    @requires_level(AccessLevel.READ)
    def summary(self, request):
        """Indicadores do funil sobre o conjunto inteiro, não só sobre a página que a tela recebeu."""
        weighted = ExpressionWrapper(
            F('value') * F('probability') / 100.0,
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        active = Q(outcome__isnull=True)
        totals = self.filter_queryset(self.get_queryset()).aggregate(
            active=Count('id', filter=active),
            total_value=Sum('value', filter=active),
            weighted_value=Sum(weighted, filter=active),
            won=Count('id', filter=Q(outcome=Deal.Outcome.WON)),
            lost=Count('id', filter=Q(outcome=Deal.Outcome.LOST)),
        )
        closed = totals['won'] + totals['lost']

        return _summary_response(
            self,
            {
                'active': totals['active'],
                'total_value': float(totals['total_value'] or 0),
                'weighted_value': float(totals['weighted_value'] or 0),
                'won': totals['won'],
                'lost': totals['lost'],
                'conversion_rate': round(totals['won'] / closed * 100) if closed else None,
            },
        )
