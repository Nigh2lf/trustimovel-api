from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.classes.permission_resource import ResourcePermission
from core.classes.permission_type_user import AllPermissionClass
from core.models import (
    Deal,
    ExporterPlan,
    Lead,
    Property,
    PropertyPrice,
    ServiceTicket,
    Task,
)

PURPOSE_ORDER = {
    PropertyPrice.Purpose.SALE: 0,
    PropertyPrice.Purpose.RENT: 1,
    PropertyPrice.Purpose.SEASONAL: 2,
}


class DashboardView(APIView):
    """Números do painel inicial, sempre restritos à imobiliária do usuário."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, AllPermissionClass, ResourcePermission]
    resource = 'dashboard'

    def get(self, request):
        properties = Property.objects.filter(
            agency_id=request.user.agency_id, deleted_at__isnull=True
        )

        totals = properties.aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(is_active=True)),
            on_site=Count("id", filter=Q(on_site=True)),
            in_condominium=Count("id", filter=Q(condominium__isnull=False)),
        )
        # O isnull=False força a existência da foto; sem ele o LEFT JOIN casaria imóvel sem foto.
        with_photo = (
            properties.filter(photos__isnull=False, photos__deleted_at__isnull=True)
            .distinct()
            .count()
        )

        data = {
            "plan": self._plan(request.user.agency),
            "properties": {
                "total": totals["total"],
                "active": totals["active"],
                "inactive": totals["total"] - totals["active"],
                "without_photo": totals["total"] - with_photo,
                "on_site": totals["on_site"],
                "off_site": totals["total"] - totals["on_site"],
            },
            "types": self._types(properties),
            "condominium": {
                "inside": totals["in_condominium"],
                "outside": totals["total"] - totals["in_condominium"],
            },
            "purposes": self._purposes(request.user.agency_id),
            "recent": self._recent(request, properties),
            "exporters": self._exporters(request.user.agency_id),
            "crm": self._crm(request.user.agency_id),
        }

        return Response(
            {"status": "success", "message": "Resumo do painel.", "data": data, "errors": []},
            status=status.HTTP_200_OK,
        )

    def _plan(self, agency):
        plan = agency.plan if agency is not None else None

        if plan is None or plan.deleted_at is not None:
            return None

        return {
            "name": plan.name,
            "property_limit": plan.property_limit,
            "photo_limit": plan.photo_limit,
        }

    def _types(self, properties):
        rows = (
            properties.filter(type__isnull=False)
            .values("type__name")
            .annotate(count=Count("id"))
            .order_by("-count", "type__name")[:3]
        )

        return [{"name": row["type__name"], "count": row["count"]} for row in rows]

    def _purposes(self, agency_id):
        rows = (
            PropertyPrice.objects.filter(
                property__agency_id=agency_id, property__deleted_at__isnull=True
            )
            .values("purpose")
            .annotate(count=Count("id"))
        )
        counts = {row["purpose"]: row["count"] for row in rows}

        return [
            {"purpose": purpose, "label": label, "count": counts.get(purpose, 0)}
            for purpose, label in PropertyPrice.Purpose.choices
        ]

    def _recent(self, request, properties):
        recent = (
            properties.select_related("type", "neighborhood__city")
            .prefetch_related("photos", "prices")
            .order_by("-created_at")[:3]
        )

        items = []

        for item in recent:
            photos = [photo for photo in item.photos.all() if photo.deleted_at is None]
            main_photo = next((photo for photo in photos if photo.is_main), photos[0] if photos else None)
            # Venda aparece primeiro quando o imóvel tem mais de uma finalidade.
            prices = sorted(item.prices.all(), key=lambda price: PURPOSE_ORDER.get(price.purpose, 9))
            price = prices[0] if prices else None

            location = ""
            if item.neighborhood_id:
                location = f"{item.neighborhood.name}, {item.neighborhood.city.name}"

            items.append(
                {
                    "id": str(item.id),
                    "code": item.code,
                    "name": item.name,
                    "location": location,
                    "photo": request.build_absolute_uri(main_photo.image.url) if main_photo else None,
                    "price": float(price.amount) if price else None,
                    "price_label": price.get_purpose_display() if price else None,
                    "area": float(item.area) if item.area is not None else None,
                    "bedrooms": item.bedrooms,
                    "bathrooms": item.bathrooms,
                    "parking_spaces": item.parking_spaces,
                    "featured": item.featured,
                    "created_at": item.created_at.date().isoformat(),
                }
            )

        return items

    def _crm(self, agency_id):
        """Resumo do dia do CRM: leads, funil, tarefas de hoje e atendimentos abertos."""
        now = timezone.localtime()
        today = now.date()

        leads = Lead.objects.filter(agency_id=agency_id, deleted_at__isnull=True)
        active_deals = Deal.objects.filter(
            agency_id=agency_id, deleted_at__isnull=True, outcome__isnull=True
        )
        pending_tasks = Task.objects.filter(
            agency_id=agency_id, deleted_at__isnull=True
        ).exclude(status=Task.Status.DONE)
        open_tickets = ServiceTicket.objects.filter(
            agency_id=agency_id,
            deleted_at__isnull=True,
            status__in=[
                ServiceTicket.Status.NEW,
                ServiceTicket.Status.IN_PROGRESS,
                ServiceTicket.Status.AWAITING_RESPONSE,
            ],
        )

        overdue = pending_tasks.filter(
            Q(due_date__lt=today)
            | Q(due_date=today, due_time__isnull=False, due_time__lt=now.time())
        ).count()

        today_tasks = (
            pending_tasks.filter(due_date=today)
            .select_related('responsible')
            .order_by('due_time')
        )

        return {
            "leads": {
                "total": leads.count(),
                "new": leads.filter(status=Lead.Status.NEW).count(),
            },
            "deals": {
                "active": active_deals.count(),
                "total_value": float(active_deals.aggregate(total=Sum("value"))["total"] or 0),
            },
            "tasks": {
                "today": today_tasks.count(),
                "overdue": overdue,
                "today_items": [
                    {
                        "id": str(task.id),
                        "title": task.title,
                        "type": task.type,
                        "due_time": task.due_time.strftime("%H:%M") if task.due_time else None,
                        "responsible_name": task.responsible.name if task.responsible_id else None,
                        "property_code": task.property_code,
                        "is_overdue": task.due_time is not None and task.due_time < now.time(),
                    }
                    for task in today_tasks
                ],
            },
            "tickets": {"open": open_tickets.count()},
        }

    def _exporters(self, agency_id):
        # Só os portais que a imobiliária configurou em Exportadores; os demais não interessam aqui.
        plans = (
            ExporterPlan.objects.filter(
                exporter__deleted_at__isnull=True,
                exporter__agency_exporters__agency_id=agency_id,
            )
            .select_related("exporter")
            .annotate(
                used=Count(
                    "properties",
                    filter=Q(
                        properties__property__agency_id=agency_id,
                        properties__property__deleted_at__isnull=True,
                    ),
                )
            )
            .order_by("exporter__name", "position", "name")
        )

        exporters = []

        for plan in plans:
            if not exporters or exporters[-1]["name"] != plan.exporter.name:
                exporters.append({"name": plan.exporter.name, "plans": []})

            exporters[-1]["plans"].append({"name": plan.name, "count": plan.used})

        return exporters
