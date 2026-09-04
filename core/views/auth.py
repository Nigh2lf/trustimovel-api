from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView

from core.serializers import LoginSerializer


class ViewTokenObtainPair(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed:
            return Response(
                {
                    "status": "error",
                    "message": "E-mail ou senha inválidos.",
                    "data": None,
                    "errors": [
                        {"field": None, "message": "E-mail ou senha inválidos."}
                    ],
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response(
            {
                "status": "success",
                "message": "Login realizado com sucesso.",
                "data": serializer.validated_data,
                "errors": [],
            },
            status=status.HTTP_200_OK,
        )
