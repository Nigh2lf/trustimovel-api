"""Validação de CPF/CNPJ e telefone dos cadastros de pessoas e do CRM."""

import re

from rest_framework import serializers

CPF_LENGTH = 11
CNPJ_LENGTH = 14


def only_digits(value):
    return re.sub(r'\D', '', value or '')


def _cpf_check_digit(digits, weights):
    total = sum(int(digit) * weight for digit, weight in zip(digits, weights))
    remainder = (total * 10) % 11

    return 0 if remainder == 10 else remainder


def is_valid_cpf(digits):
    if len(digits) != CPF_LENGTH or len(set(digits)) == 1:
        return False

    first = _cpf_check_digit(digits[:9], range(10, 1, -1))
    second = _cpf_check_digit(digits[:10], range(11, 1, -1))

    return digits[9:] == f'{first}{second}'


def _cnpj_check_digit(digits, weights):
    total = sum(int(digit) * weight for digit, weight in zip(digits, weights))
    remainder = total % 11

    return 0 if remainder < 2 else 11 - remainder


def is_valid_cnpj(digits):
    if len(digits) != CNPJ_LENGTH or len(set(digits)) == 1:
        return False

    first = _cnpj_check_digit(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    second = _cnpj_check_digit(digits[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])

    return digits[12:] == f'{first}{second}'


def format_document(digits):
    """Máscara padrão, a mesma que as telas mostram: 000.000.000-00 ou 00.000.000/0000-00."""
    if len(digits) == CPF_LENGTH:
        return f'{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}'

    return f'{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}'


def clean_document(value):
    """Devolve o CPF/CNPJ já formatado, ou vazio; recusa dígito verificador inválido."""
    digits = only_digits(value)

    if not digits:
        return ''

    if len(digits) == CPF_LENGTH and is_valid_cpf(digits):
        return format_document(digits)

    if len(digits) == CNPJ_LENGTH and is_valid_cnpj(digits):
        return format_document(digits)

    raise serializers.ValidationError('Informe um CPF ou CNPJ válido.')


def document_lookup_values(document):
    """Formas como o mesmo documento pode estar gravado, para a busca de duplicidade."""
    digits = only_digits(document)

    return {document, digits, format_document(digits)}


def clean_phone(value):
    """Telefone com DDD: 10 dígitos no fixo, 11 no celular. Vazio continua vazio."""
    stripped = (value or '').strip()

    if not stripped:
        return ''

    digits = only_digits(stripped)

    if len(digits) < 10 or len(digits) > 13:
        raise serializers.ValidationError('Informe o telefone com DDD, ex.: (21) 99999-9999.')

    return stripped
