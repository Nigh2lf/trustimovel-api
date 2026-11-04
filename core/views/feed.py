from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.models import Agency, AgencyExporter, Exporter
from core.services.property_feed import build_feed, feed_properties, is_valid_feed_key


class PropertyFeedView(APIView):
    """Feed XML lido pelo portal: público de propósito, a chave na URL faz as vezes do login."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'feed'

    def get(self, request, agency_slug, key, exporter_slug, scope='marked'):
        agency = get_object_or_404(
            Agency, slug=agency_slug, is_active=True, deleted_at__isnull=True
        )

        # Chave errada responde como se nada existisse, sem confirmar a imobiliária.
        if not is_valid_feed_key(agency, key):
            raise Http404

        exporter = get_object_or_404(
            Exporter, slug=exporter_slug, is_active=True, deleted_at__isnull=True
        )

        # Portal desativado em Integrações derruba os dois links na hora.
        if not AgencyExporter.objects.filter(agency=agency, exporter=exporter).exists():
            raise Http404

        properties = feed_properties(agency=agency, exporter=exporter, include_all=scope == 'all')
        xml = build_feed(agency=agency, properties=properties, request=request)

        return HttpResponse(xml, content_type='application/xml; charset=utf-8')
