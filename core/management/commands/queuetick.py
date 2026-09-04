from django.core.management.base import BaseCommand

from core.models import Lead
from core.services import queue as queue_service


class Command(BaseCommand):
    help = (
        'Passa o relógio da fila de atendimento: expira ofertas, transfere quem estourou o SLA '
        'e redistribui quem está na espera. Para rodar no cron, a cada minuto.'
    )

    def handle(self, *args, **options):
        agency_ids = (
            Lead.objects.filter(deleted_at__isnull=True, queue_status__in=queue_service.OPEN_STATUSES)
            .values_list('agency_id', flat=True)
            .distinct()
        )

        total = 0
        for agency_id in agency_ids:
            queue_service.tick(agency_id)
            total += 1

        self.stdout.write(f'Fila processada em {total} imobiliária(s).')
