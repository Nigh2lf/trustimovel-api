from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.classes.permission_resource import ResourcePermission
from core.classes.permission_type_user import AllPermissionClass
from core.models import AgencySettings
from core.serializers import AgencySettingsSerializer


class AgencySettingsView(APIView):
    """Configurações da imobiliária: um único registro por conta, criado no primeiro acesso."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, AllPermissionClass, ResourcePermission]
    resource = 'configuracoes'

    def get(self, request):
        settings = self._get_settings(request)

        if settings is None:
            return self._no_agency_response()

        serializer = AgencySettingsSerializer(settings)

        return Response(
            {
                "status": "success",
                "message": "Configurações da imobiliária.",
                "data": serializer.data,
                "errors": [],
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        settings = self._get_settings(request)

        if settings is None:
            return self._no_agency_response()

        serializer = AgencySettingsSerializer(settings, data=request.data, partial=True)

        if not serializer.is_valid():
            return Response(
                {
                    "status": "error",
                    "message": "Dados inválidos.",
                    "data": None,
                    "errors": [
                        {"field": field, "message": str(messages[0])}
                        for field, messages in serializer.errors.items()
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer.save()

        return Response(
            {
                "status": "success",
                "message": "Configurações salvas com sucesso.",
                "data": serializer.data,
                "errors": [],
            },
            status=status.HTTP_200_OK,
        )

    def _get_settings(self, request):
        if request.user.agency_id is None:
            return None

        settings, _ = AgencySettings.objects.get_or_create(agency_id=request.user.agency_id)

        return settings

    def _no_agency_response(self):
        return Response(
            {
                "status": "error",
                "message": "Seu usuário não está vinculado a uma imobiliária.",
                "data": None,
                "errors": [],
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
