from rest_framework import serializers

from core.models import AgencySettings, Lead, LeadInteraction, User
from core.services.queue import ATTEMPT_EVENTS


class QueueSettingsSerializer(serializers.ModelSerializer):
    """As regras da fila sem o prefixo `queue_` do model: é o vocabulário da tela de configuração."""

    mode = serializers.ChoiceField(source='queue_mode', choices=AgencySettings.QueueMode.choices)
    auto_assign = serializers.BooleanField(source='queue_auto_assign')
    decline_behavior = serializers.ChoiceField(
        source='queue_decline_behavior', choices=AgencySettings.QueueDeclineBehavior.choices
    )
    accept_minutes = serializers.IntegerField(source='queue_accept_minutes', min_value=1, max_value=1440)
    first_response_minutes = serializers.IntegerField(
        source='queue_first_response_minutes', min_value=1, max_value=1440
    )
    max_active_per_broker = serializers.IntegerField(
        source='queue_max_active_per_broker', min_value=0, max_value=100
    )
    return_window_days = serializers.IntegerField(source='queue_return_window_days', min_value=0, max_value=365)
    skips_before_pause = serializers.IntegerField(source='queue_skips_before_pause', min_value=0, max_value=100)
    business_start = serializers.TimeField(source='queue_business_start', format='%H:%M')
    business_end = serializers.TimeField(source='queue_business_end', format='%H:%M')
    business_days = serializers.ListField(
        source='queue_business_days', child=serializers.IntegerField(min_value=0, max_value=6)
    )
    off_hours = serializers.ChoiceField(source='queue_off_hours', choices=AgencySettings.QueueOffHours.choices)

    class Meta:
        model = AgencySettings
        fields = [
            'mode',
            'auto_assign',
            'decline_behavior',
            'accept_minutes',
            'first_response_minutes',
            'max_active_per_broker',
            'return_window_days',
            'skips_before_pause',
            'business_start',
            'business_end',
            'business_days',
            'off_hours',
        ]

    def validate_business_days(self, value):
        return sorted(set(value))

    def validate(self, attrs):
        start = attrs.get('queue_business_start', getattr(self.instance, 'queue_business_start', None))
        end = attrs.get('queue_business_end', getattr(self.instance, 'queue_business_end', None))

        if start and end and end <= start:
            raise serializers.ValidationError(
                {'business_end': 'O fim do expediente precisa ser depois do início.'}
            )

        return attrs


class QueueBrokerSerializer(serializers.ModelSerializer):
    presence = serializers.CharField(source='queue_presence', read_only=True)
    presence_label = serializers.CharField(source='get_queue_presence_display', read_only=True)
    pause_reason = serializers.CharField(source='queue_pause_reason', read_only=True)
    order = serializers.IntegerField(source='queue_order', read_only=True)
    skips = serializers.IntegerField(source='queue_skips', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'team', 'presence', 'presence_label', 'pause_reason', 'in_queue', 'order', 'skips']
        read_only_fields = fields


class QueueEventSerializer(serializers.ModelSerializer):
    type_label = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = LeadInteraction
        fields = ['id', 'type', 'type_label', 'user', 'author_name', 'text', 'created_at']
        read_only_fields = fields


class QueueLeadSerializer(serializers.ModelSerializer):
    source_label = serializers.CharField(source='get_source_display', read_only=True)
    interest_label = serializers.CharField(source='get_interest_display', read_only=True)
    queue_status_label = serializers.CharField(source='get_queue_status_display', read_only=True)
    outcome = serializers.SerializerMethodField()
    attempts = serializers.SerializerMethodField()
    events = QueueEventSerializer(source='interactions', many=True, read_only=True)

    class Meta:
        model = Lead
        fields = [
            'id',
            'code',
            'name',
            'phone',
            'email',
            'source',
            'source_label',
            'interest',
            'interest_label',
            'city',
            'budget',
            'observations',
            'status',
            'queue_status',
            'queue_status_label',
            'assigned_to',
            'queue_reason',
            'created_at',
            'offered_at',
            'accepted_at',
            'contacted_at',
            'queue_closed_at',
            'deadline_at',
            'sla_breached',
            'outcome',
            'attempts',
            'events',
        ]
        read_only_fields = fields

    def get_outcome(self, lead):
        if lead.queue_status != Lead.QueueStatus.CLOSED:
            return None

        won = lead.status in (Lead.Status.QUALIFIED, Lead.Status.CONVERTED)
        return 'WON' if won else 'LOST'

    def get_attempts(self, lead):
        # Lê do prefetch de `interactions`, para a listagem não fazer uma consulta por lead.
        return sorted(
            {
                str(event.user_id)
                for event in lead.interactions.all()
                if event.user_id and event.type in ATTEMPT_EVENTS
            }
        )


class EnqueueSerializer(serializers.Serializer):
    lead = serializers.UUIDField()


class DeclineSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class CloseSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=['WON', 'LOST'])
    detail = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AssignSerializer(serializers.Serializer):
    user = serializers.UUIDField()


class ReturnSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class NoteSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000)


class PresenceSerializer(serializers.Serializer):
    presence = serializers.ChoiceField(choices=User.QueuePresence.choices)
    pause_reason = serializers.CharField(required=False, allow_blank=True, max_length=150)


class MoveSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(choices=[-1, 1])
