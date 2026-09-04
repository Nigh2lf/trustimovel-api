from rest_framework import status as http_status
from rest_framework.response import Response


def success_response(data=None, message='', status=http_status.HTTP_200_OK):
    """Envelope padrão de sucesso dos endpoints novos (ver "Padrão de resposta da API")."""
    return Response(
        {'status': 'success', 'message': message, 'data': data, 'errors': []},
        status=status,
    )


def error_response(message, errors=None, status=http_status.HTTP_400_BAD_REQUEST):
    return Response(
        {'status': 'error', 'message': message, 'data': None, 'errors': errors or []},
        status=status,
    )


def serializer_errors(serializer):
    """Erros do DRF no formato de lista {field, message} que o envelope usa."""
    return [
        {'field': field, 'message': str(messages[0] if isinstance(messages, list) else messages)}
        for field, messages in serializer.errors.items()
    ]
