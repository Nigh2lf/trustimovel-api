from django.utils import timezone
from rest_framework import serializers

from core.models import Deal, Lead, LeadInteraction, ServiceTicket, ServiceTicketMessage, Task, User


class LeadInteractionSerializer(serializers.ModelSerializer):
    type_label = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = LeadInteraction
        fields = ['id', 'type', 'type_label', 'user', 'author_name', 'text', 'created_at']
        read_only_fields = ['id', 'type', 'user', 'author_name', 'created_at']


class LeadSerializer(serializers.ModelSerializer):
    source_label = serializers.CharField(source='get_source_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    interest_label = serializers.CharField(source='get_interest_display', read_only=True)
    responsible_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    queue_status_label = serializers.CharField(source='get_queue_status_display', read_only=True)
    interactions = LeadInteractionSerializer(many=True, read_only=True)

    class Meta:
        model = Lead
        fields = [
            'id',
            'code',
            'name',
            'email',
            'phone',
            'source',
            'source_label',
            'status',
            'status_label',
            'interest',
            'interest_label',
            'property_type',
            'budget',
            'city',
            'state',
            'responsible',
            'responsible_name',
            'assigned_to',
            'assigned_to_name',
            'queue_status',
            'queue_status_label',
            'observations',
            'last_contact_at',
            'interactions',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'code', 'queue_status', 'last_contact_at', 'created_at', 'updated_at']

    def get_responsible_name(self, lead):
        return lead.responsible.name if lead.responsible_id else None

    def get_assigned_to_name(self, lead):
        if not lead.assigned_to_id:
            return None

        return lead.assigned_to.name or lead.assigned_to.email

    def validate_assigned_to(self, value):
        # Só corretor (usuário) da própria imobiliária fica com o lead.
        request = self.context.get('request')

        if value is None or request is None:
            return value

        if value.agency_id != request.user.agency_id or value.type != User.Type.BROKER:
            raise serializers.ValidationError('Corretor não encontrado.')

        return value

    def validate_responsible(self, value):
        # Corretor de outra imobiliária não pode ser responsável aqui.
        request = self.context.get('request')

        if value is not None and request is not None and value.agency_id != request.user.agency_id:
            raise serializers.ValidationError('Corretor não encontrado.')

        return value


class ServiceTicketMessageSerializer(serializers.ModelSerializer):
    author_type_label = serializers.CharField(source='get_author_type_display', read_only=True)

    class Meta:
        model = ServiceTicketMessage
        fields = ['id', 'author_name', 'author_type', 'author_type_label', 'message', 'created_at']
        read_only_fields = ['id', 'author_name', 'created_at']


class ServiceTicketSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source='get_category_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    priority_label = serializers.CharField(source='get_priority_display', read_only=True)
    responsible_name = serializers.SerializerMethodField()
    messages = ServiceTicketMessageSerializer(many=True, read_only=True)
    messages_count = serializers.IntegerField(source='messages.count', read_only=True)

    class Meta:
        model = ServiceTicket
        fields = [
            'id',
            'protocol',
            'client_name',
            'email',
            'phone',
            'subject',
            'category',
            'category_label',
            'status',
            'status_label',
            'priority',
            'priority_label',
            'responsible',
            'responsible_name',
            'property_code',
            'description',
            'messages',
            'messages_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'protocol', 'created_at', 'updated_at']

    def get_responsible_name(self, ticket):
        return ticket.responsible.name if ticket.responsible_id else None

    def validate_responsible(self, value):
        request = self.context.get('request')

        if value is not None and request is not None and value.agency_id != request.user.agency_id:
            raise serializers.ValidationError('Corretor não encontrado.')

        return value


class TaskSerializer(serializers.ModelSerializer):
    type_label = serializers.CharField(source='get_type_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    priority_label = serializers.CharField(source='get_priority_display', read_only=True)
    responsible_name = serializers.SerializerMethodField()
    related_label = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'id',
            'title',
            'description',
            'type',
            'type_label',
            'status',
            'status_label',
            'priority',
            'priority_label',
            'responsible',
            'responsible_name',
            'due_date',
            'due_time',
            'lead',
            'deal',
            'related_label',
            'property_code',
            'notes',
            'is_overdue',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_responsible_name(self, task):
        return task.responsible.name if task.responsible_id else None

    def get_related_label(self, task):
        if task.lead_id:
            return f'Lead {task.lead.code} — {task.lead.name}'

        if task.deal_id:
            return f'Negócio — {task.deal.title}'

        return ''

    def get_is_overdue(self, task):
        if task.status == Task.Status.DONE or task.due_date is None:
            return False

        now = timezone.localtime()

        if task.due_date < now.date():
            return True

        return task.due_date == now.date() and task.due_time is not None and task.due_time < now.time()

    def validate(self, attrs):
        current = self.instance

        def value_of(field):
            if field in attrs:
                return attrs[field]
            return getattr(current, field, None)

        if value_of('type') == Task.Type.VISIT and not value_of('property_code'):
            raise serializers.ValidationError({'property_code': 'Informe o imóvel da visita.'})

        for field in ('responsible', 'lead', 'deal'):
            related = attrs.get(field)
            request = self.context.get('request')

            if related is not None and request is not None and related.agency_id != request.user.agency_id:
                raise serializers.ValidationError({field: 'Registro não encontrado.'})

        return attrs


class DealSerializer(serializers.ModelSerializer):
    stage_label = serializers.CharField(source='get_stage_display', read_only=True)
    type_label = serializers.CharField(source='get_type_display', read_only=True)
    origin_label = serializers.CharField(source='get_origin_display', read_only=True)
    outcome_label = serializers.CharField(source='get_outcome_display', read_only=True)
    loss_reason_label = serializers.CharField(source='get_loss_reason_display', read_only=True)
    responsible_name = serializers.SerializerMethodField()

    class Meta:
        model = Deal
        fields = [
            'id',
            'title',
            'client_name',
            'value',
            'stage',
            'stage_label',
            'probability',
            'estimated_close',
            'responsible',
            'responsible_name',
            'origin',
            'origin_label',
            'type',
            'type_label',
            'property_code',
            'description',
            'notes',
            'outcome',
            'outcome_label',
            'loss_reason',
            'loss_reason_label',
            'closed_at',
            'lead',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'closed_at', 'lead', 'created_at', 'updated_at']

    def get_responsible_name(self, deal):
        return deal.responsible.name if deal.responsible_id else None

    def validate_probability(self, value):
        if not 0 <= value <= 100:
            raise serializers.ValidationError('A probabilidade precisa estar entre 0 e 100.')

        return value

    def validate_responsible(self, value):
        request = self.context.get('request')

        if value is not None and request is not None and value.agency_id != request.user.agency_id:
            raise serializers.ValidationError('Corretor não encontrado.')

        return value

    def validate(self, attrs):
        outcome = attrs.get('outcome', self.instance.outcome if self.instance else None)

        if outcome == Deal.Outcome.LOST:
            loss_reason = attrs.get(
                'loss_reason', self.instance.loss_reason if self.instance else ''
            )

            if not loss_reason:
                raise serializers.ValidationError({'loss_reason': 'Informe o motivo da perda.'})

        return attrs

    def update(self, instance, validated_data):
        # Encerrar carimba a data; reabrir limpa desfecho, motivo e data de uma vez.
        if 'outcome' in validated_data:
            outcome = validated_data['outcome']

            if outcome is None:
                validated_data['loss_reason'] = ''
                instance.closed_at = None
            elif instance.outcome != outcome and instance.closed_at is None:
                instance.closed_at = timezone.localdate()

            if outcome == Deal.Outcome.WON:
                validated_data['loss_reason'] = ''

        return super().update(instance, validated_data)
