from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.classes.permission_resource import ResourcePermission
from core.classes.permission_type_user import AllPermissionClass
from core.models import Broker, Deal, Lead, Property, PropertyPrice

MONTH_ABBR = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']

MAX_PERIOD_DAYS = 1830

DEFAULT_PERIOD_MONTHS = 5


class ReportsView(APIView):
    """Números da tela de Relatórios, sempre restritos à imobiliária do usuário."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, AllPermissionClass, ResourcePermission]
    resource = 'relatorios'

    def get(self, request):
        try:
            start, end = self._period(request)
        except ValueError as exc:
            return Response(
                {
                    'status': 'error',
                    'message': str(exc),
                    'data': None,
                    'errors': [{'field': 'start', 'message': str(exc)}],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        agency_id = request.user.agency_id
        previous_start, previous_end = self._previous_period(start, end)
        current = self._closing_numbers(agency_id, start, end)
        previous = self._closing_numbers(agency_id, previous_start, previous_end)

        data = {
            'period': {'start': start.isoformat(), 'end': end.isoformat()},
            'summary': {
                'current': current,
                'previous': previous,
                'changes': {
                    key: self._change(current[key], previous[key]) for key in current
                },
            },
            'sales': self._sales(agency_id, start, end),
            'properties': self._properties(agency_id, start, end),
            'leads': self._leads(agency_id, start, end),
            'brokers': self._brokers(agency_id, start, end),
            'funnel': self._funnel(agency_id, start, end),
        }

        return Response(
            {
                'status': 'success',
                'message': 'Relatório do período.',
                'data': data,
                'errors': [],
            },
            status=status.HTTP_200_OK,
        )

    def _period(self, request):
        end = self._parse_date(request.query_params.get('end'), timezone.localdate())
        start = self._parse_date(
            request.query_params.get('start'), self._month_start(end, DEFAULT_PERIOD_MONTHS)
        )

        if start > end:
            raise ValueError('A data inicial precisa ser anterior à data final.')

        if (end - start).days > MAX_PERIOD_DAYS:
            raise ValueError('Escolha um período de no máximo cinco anos.')

        return start, end

    def _parse_date(self, value, fallback):
        if not value:
            return fallback

        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError('Informe as datas no formato AAAA-MM-DD.')

    def _month_start(self, reference, months_back):
        index = reference.year * 12 + reference.month - 1 - months_back

        return date(index // 12, index % 12 + 1, 1)

    def _previous_period(self, start, end):
        """Mesma duração imediatamente antes do período, para a comparação percentual."""
        previous_end = start - timedelta(days=1)

        return previous_end - (end - start), previous_end

    def _created_between(self, start, end):
        """Limites em datetime: o lookup __date dependeria do CONVERT_TZ do MySQL."""
        begin = timezone.make_aware(datetime.combine(start, time.min))
        finish = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min))

        return Q(created_at__gte=begin, created_at__lt=finish)

    def _change(self, current, previous):
        """Sem base de comparação o percentual não existe — a tela mostra um traço."""
        if not previous:
            return None

        return round((current / previous - 1) * 100, 1)

    def _closing_numbers(self, agency_id, start, end):
        closed = Deal.objects.filter(
            agency_id=agency_id, deleted_at__isnull=True, closed_at__range=(start, end)
        ).aggregate(
            won_count=Count('id', filter=Q(outcome=Deal.Outcome.WON)),
            won_value=Sum('value', filter=Q(outcome=Deal.Outcome.WON)),
            lost_count=Count('id', filter=Q(outcome=Deal.Outcome.LOST)),
        )

        won_count = closed['won_count']
        won_value = float(closed['won_value'] or 0)
        decided = won_count + closed['lost_count']

        return {
            'total_value': won_value,
            'total_count': won_count,
            'average_ticket': won_value / won_count if won_count else 0.0,
            'conversion_rate': round(won_count / decided * 100, 1) if decided else 0.0,
        }

    def _sales(self, agency_id, start, end):
        totals = {
            row['month']: row
            for row in Deal.objects.filter(
                agency_id=agency_id,
                deleted_at__isnull=True,
                outcome=Deal.Outcome.WON,
                closed_at__range=(start, end),
            )
            .annotate(month=TruncMonth('closed_at'))
            .values('month')
            .annotate(value=Sum('value'), count=Count('id'))
        }

        monthly = []

        for month in self._months_between(start, end):
            row = totals.get(month)
            monthly.append(
                {
                    'month': month.isoformat(),
                    'label': f'{MONTH_ABBR[month.month - 1]}/{month:%y}',
                    'value': float(row['value']) if row else 0.0,
                    'count': row['count'] if row else 0,
                }
            )

        return {'monthly': monthly}

    def _months_between(self, start, end):
        months = []
        current = start.replace(day=1)

        while current <= end:
            months.append(current)
            current = date(current.year + current.month // 12, current.month % 12 + 1, 1)

        return months

    def _properties(self, agency_id, start, end):
        properties = Property.objects.filter(agency_id=agency_id, deleted_at__isnull=True)

        sale_totals = {
            row['property__type__name']: row
            for row in PropertyPrice.objects.filter(
                property__agency_id=agency_id,
                property__deleted_at__isnull=True,
                purpose=PropertyPrice.Purpose.SALE,
            )
            .values('property__type__name')
            .annotate(total=Sum('amount'), count=Count('id'))
        }

        by_type = []

        for row in properties.values('type__name').annotate(count=Count('id')).order_by('-count'):
            sale = sale_totals.get(row['type__name'])
            value = float(sale['total']) if sale else 0.0
            sale_count = sale['count'] if sale else 0

            by_type.append(
                {
                    'name': row['type__name'] or 'Sem tipo',
                    'count': row['count'],
                    'sale_count': sale_count,
                    'value': value,
                    'average': value / sale_count if sale_count else 0.0,
                }
            )

        totals = properties.aggregate(
            total=Count('id'), active=Count('id', filter=Q(is_active=True))
        )

        return {
            'total': totals['total'],
            'active': totals['active'],
            'inactive': totals['total'] - totals['active'],
            'created_in_period': properties.filter(self._created_between(start, end)).count(),
            'by_type': by_type,
        }

    def _leads(self, agency_id, start, end):
        leads = Lead.objects.filter(agency_id=agency_id, deleted_at__isnull=True).filter(
            self._created_between(start, end)
        )

        by_source = self._counts_by_choice(leads, 'source', Lead.Source.choices)
        by_status = self._counts_by_choice(leads, 'status', Lead.Status.choices)
        total = sum(item['count'] for item in by_source)
        converted = next(
            (item['count'] for item in by_status if item['value'] == Lead.Status.CONVERTED), 0
        )

        return {
            'total': total,
            'converted': converted,
            'conversion_rate': round(converted / total * 100, 1) if total else 0.0,
            'by_source': by_source,
            'by_status': by_status,
        }

    def _counts_by_choice(self, queryset, field, choices):
        counts = {
            row[field]: row['count'] for row in queryset.values(field).annotate(count=Count('id'))
        }

        return [
            {'value': value, 'label': label, 'count': counts.get(value, 0)}
            for value, label in choices
        ]

    def _brokers(self, agency_id, start, end):
        won = Q(outcome=Deal.Outcome.WON, closed_at__range=(start, end))
        lost = Q(outcome=Deal.Outcome.LOST, closed_at__range=(start, end))
        still_open = Q(outcome__isnull=True)

        # Duas consultas em vez de uma: negócios e leads no mesmo JOIN duplicariam as somas.
        deals = {
            row['responsible_id']: row
            for row in Deal.objects.filter(agency_id=agency_id, deleted_at__isnull=True)
            .values('responsible_id')
            .annotate(
                won_count=Count('id', filter=won),
                won_value=Sum('value', filter=won),
                lost_count=Count('id', filter=lost),
                open_count=Count('id', filter=still_open),
                open_value=Sum('value', filter=still_open),
            )
        }
        leads = {
            row['responsible_id']: row['count']
            for row in Lead.objects.filter(agency_id=agency_id, deleted_at__isnull=True)
            .filter(self._created_between(start, end))
            .values('responsible_id')
            .annotate(count=Count('id'))
        }
        names = dict(Broker.objects.filter(agency_id=agency_id).values_list('id', 'name'))

        items = []

        for broker_id in set(deals) | set(leads):
            row = deals.get(broker_id, {})
            won_count = row.get('won_count', 0)
            won_value = float(row.get('won_value') or 0)
            lost_count = row.get('lost_count', 0)
            decided = won_count + lost_count

            items.append(
                {
                    'id': str(broker_id) if broker_id else None,
                    'name': names.get(broker_id) or 'Sem responsável',
                    'won_count': won_count,
                    'won_value': won_value,
                    'average_ticket': won_value / won_count if won_count else 0.0,
                    'lost_count': lost_count,
                    'conversion_rate': round(won_count / decided * 100, 1) if decided else 0.0,
                    'open_count': row.get('open_count', 0),
                    'open_value': float(row.get('open_value') or 0),
                    'leads_count': leads.get(broker_id, 0),
                }
            )

        items.sort(key=lambda item: (-item['won_value'], -item['won_count'], item['name']))

        return items

    def _funnel(self, agency_id, start, end):
        deals = Deal.objects.filter(agency_id=agency_id, deleted_at__isnull=True).filter(
            self._created_between(start, end)
        )

        by_stage = {
            row['stage']: row
            for row in deals.values('stage').annotate(count=Count('id'), value=Sum('value'))
        }
        stages = [value for value, _ in Deal.Stage.choices]
        labels = dict(Deal.Stage.choices)
        total = sum(row['count'] for row in by_stage.values())

        items = []

        for index, stage in enumerate(stages):
            # Quem está num estágio já passou pelos anteriores: o alcance é acumulado daqui em diante.
            reached = [by_stage[later] for later in stages[index:] if later in by_stage]
            count = sum(row['count'] for row in reached)

            items.append(
                {
                    'stage': stage,
                    'label': labels[stage],
                    'count': count,
                    'value': sum(float(row['value'] or 0) for row in reached),
                    'conversion': round(count / total * 100, 1) if total else 0.0,
                }
            )

        outcomes = deals.aggregate(
            open_count=Count('id', filter=Q(outcome__isnull=True)),
            open_value=Sum('value', filter=Q(outcome__isnull=True)),
            won_count=Count('id', filter=Q(outcome=Deal.Outcome.WON)),
            won_value=Sum('value', filter=Q(outcome=Deal.Outcome.WON)),
            lost_count=Count('id', filter=Q(outcome=Deal.Outcome.LOST)),
            lost_value=Sum('value', filter=Q(outcome=Deal.Outcome.LOST)),
        )
        decided = outcomes['won_count'] + outcomes['lost_count']
        loss_labels = dict(Deal.LossReason.choices)

        loss_reasons = sorted(
            [
                {
                    'reason': row['loss_reason'],
                    'label': loss_labels.get(row['loss_reason'], 'Não informado'),
                    'count': row['count'],
                }
                for row in deals.filter(outcome=Deal.Outcome.LOST)
                .values('loss_reason')
                .annotate(count=Count('id'))
            ],
            key=lambda item: -item['count'],
        )

        return {
            'total': total,
            'stages': items,
            'outcomes': {
                'open': {
                    'count': outcomes['open_count'],
                    'value': float(outcomes['open_value'] or 0),
                },
                'won': {
                    'count': outcomes['won_count'],
                    'value': float(outcomes['won_value'] or 0),
                },
                'lost': {
                    'count': outcomes['lost_count'],
                    'value': float(outcomes['lost_value'] or 0),
                },
                'conversion_rate': (
                    round(outcomes['won_count'] / decided * 100, 1) if decided else 0.0
                ),
            },
            'loss_reasons': loss_reasons,
        }
