from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.services.address import AddressLookupError, find_or_create_address


class AddressLookupView(APIView):
    """Busca o CEP no ViaCEP e devolve o endereço já casado com o catálogo local."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "address_lookup"

    def get(self, request):
        try:
            data = find_or_create_address(zip_code=request.query_params.get("zip_code", ""))
        except AddressLookupError as exc:
            return Response(
                {
                    "status": "error",
                    "message": str(exc),
                    "data": None,
                    "errors": [{"field": "zip_code", "message": str(exc)}],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "status": "success",
                "message": "Endereço encontrado.",
                "data": data,
                "errors": [],
            },
            status=status.HTTP_200_OK,
        )
