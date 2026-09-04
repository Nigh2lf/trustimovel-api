from rest_framework import fields, serializers

# O catálogo pt-BR do DRF não traduz tudo; estas são as mensagens que sobraram em inglês.
PORTUGUESE_MESSAGES = {
    fields.BooleanField: {
        'invalid': 'Informe um valor verdadeiro ou falso.',
    },
    fields.CharField: {
        'invalid': 'Informe um texto válido.',
    },
    fields.SlugField: {
        'invalid_unicode': 'Informe um identificador válido, com letras, números, hífen ou sublinhado.',
    },
    fields.UUIDField: {
        'invalid': 'Informe um identificador válido.',
    },
    fields.DateTimeField: {
        'make_aware': 'Data e hora inválidas para o fuso "{timezone}".',
        'overflow': 'Data e hora fora do intervalo aceito.',
    },
    fields.ListField: {
        'min_length': 'Envie pelo menos {min_length} item(ns).',
        'max_length': 'Envie no máximo {max_length} item(ns).',
    },
    fields.DictField: {
        'empty': 'Este campo não pode ser enviado vazio.',
    },
    serializers.ListSerializer: {
        'min_length': 'Envie pelo menos {min_length} item(ns).',
        'max_length': 'Envie no máximo {max_length} item(ns).',
    },
}


def apply_portuguese_messages():
    """Completa em português as mensagens do DRF antes de qualquer serializer ser montado."""
    serializers.ValidationError.default_detail = 'Dados inválidos.'
    fields.ProhibitSurrogateCharactersValidator.message = (
        'O texto tem caracteres não aceitos: U+{code_point:X}.'
    )

    for field_class, messages in PORTUGUESE_MESSAGES.items():
        field_class.default_error_messages = {
            **field_class.default_error_messages,
            **messages,
        }
