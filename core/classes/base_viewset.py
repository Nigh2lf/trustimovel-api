import ast
import logging
from django.forms import ValidationError
from django.http import JsonResponse
from rest_framework import viewsets
from rest_framework import status
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from django.db import transaction

logger = logging.getLogger(__name__)


class BaseViewSet(viewsets.ModelViewSet):
    def dispatch(self, request, *args, **kwargs):
        try:
            res = super().dispatch(request, *args, **kwargs)
            if res.status_code >= 400:
                return JsonResponse(
                    {
                        "success": False,
                        "message": self._error_message(res),
                        "data": {},
                        "error": res.data,
                        "status": res.status_code,
                    },
                    status=res.status_code,
                )
            return res
        except PermissionDenied as e:
            # 403, e não 401: o usuário está autenticado, apenas não tem acesso ao recurso.
            # O front trata 401 como sessão expirada e desloga; trocar um pelo outro
            # expulsaria da aplicação quem só esbarrou numa permissão.
            return JsonResponse(
                {
                    "success": False,
                    "message": self._permission_message(e.detail),
                    "data": {},
                    "error": None,
                    "status": status.HTTP_403_FORBIDDEN,
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as e:
            error, message = e.args
            error_dict = ast.literal_eval(str(error))
            return JsonResponse(
                {
                    "success": False,
                    "message": message,
                    "data": {},
                    "error": error_dict,
                    "status": status.HTTP_400_BAD_REQUEST,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            # A mensagem do Python sairia em inglês e com detalhe interno; o traceback fica no log.
            logger.exception('Erro inesperado em %s', request.path)

            return JsonResponse(
                {
                    "success": False,
                    "message": "Não foi possível completar a operação.",
                    "data": {},
                    "error": None,
                    "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        res = super(BaseViewSet, self).create(request, *args, **kwargs)
        return self._response_format(True, res.status_code, data=res.data)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        res = super(BaseViewSet, self).update(request, *args, **kwargs)
        return self._response_format(True, res.status_code, data=res.data)

    def list(self, request, *args, **kwargs):
        res = super(BaseViewSet, self).list(request, *args, **kwargs)
        return self._response_format(True, res.status_code, data=res.data)

    def retrieve(self, request, *args, **kwargs):
        res = super(BaseViewSet, self).retrieve(request, *args, **kwargs)
        return self._response_format(True, res.status_code, data=res.data)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        res = super(BaseViewSet, self).destroy(request, *args, **kwargs)
        return self._response_format(
            True, res.status_code, message="Registro deletado com sucesso!"
        )

    def perform_destroy(self, instance):
        instance.delete(deleted_by=self.request.user)

    def _permission_message(self, detail):
        """As classes de permissão levantam PermissionDenied com o envelope inteiro no detail."""
        if isinstance(detail, dict):
            for key in ("message", "detail"):
                if detail.get(key):
                    return str(detail[key])

            return "Sem permissão para acessar o recurso."

        return str(detail) if detail else "Sem permissão para acessar o recurso."

    def _error_message(self, res):
        """Mensagem do envelope de erro, preservando o texto da permissão quando houver."""
        if res.status_code == status.HTTP_403_FORBIDDEN:
            return self._permission_message(getattr(res, "data", None))

        return "Não foi possível completar a operação."

    def _response_format(self, success, status, message=None, data=None, error=None):
        response = {
            "success": success,
            "status": status,
            "message": message,
            "data": data,
            "error": error,
        }

        if success:
            return Response(response, status=status)
        else:
            return Response(response, status=status)
