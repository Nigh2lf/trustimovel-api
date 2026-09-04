from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
import getpass

User = get_user_model()


class Command(BaseCommand):
    help = 'Cria um usuário com e-mail e senha'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            dest='email',
            help='E-mail do usuário',
        )
        parser.add_argument(
            '--password',
            dest='password',
            help='Senha do usuário',
        )
        parser.add_argument(
            '--no-input',
            action='store_true',
            dest='no_input',
            help='Modo não interativo. Falha se o e-mail ou a senha não forem informados.',
        )
        parser.add_argument(
            '--no-validate',
            action='store_true',
            dest='no_validate',
            help='Não valida a força da senha (aceita senhas fracas)',
        )

    def handle(self, *args, **options):
        email = options.get('email')
        password = options.get('password')
        no_input = options.get('no_input')
        no_validate = options.get('no_validate')

        # Interactive mode
        if not no_input:
            if not email:
                email = self._get_email_input()
            
            if not password:
                password = self._get_password_input()
        
        # Validate inputs
        if not email:
            raise CommandError('Informe o e-mail.')

        if not password:
            raise CommandError('Informe a senha.')

        # Check if user already exists
        if User.objects.filter(email=email).exists():
            raise CommandError(f'Já existe um usuário com o e-mail "{email}".')

        # Validate password strength (unless --no-validate is used)
        if not no_validate:
            try:
                validate_password(password)
            except ValidationError as e:
                raise CommandError('\n'.join(e.messages))

        # Create user
        try:
            user = User.objects.create_user(
                email=email,
                password=password,
            )
            user.type='ADMIN'
            user.save()
            self.stdout.write(
                self.style.SUCCESS(f'Usuário "{email}" criado com sucesso, do tipo ADMIN.')
            )
        except Exception as e:
            raise CommandError(f'Não foi possível criar o usuário: {str(e)}')

    def _get_email_input(self):
        """Get email from user input with validation"""
        while True:
            email = input('E-mail: ').strip()
            if email:
                return email
            self.stderr.write('Informe o e-mail.')

    def _get_password_input(self):
        """Get password from user input with confirmation"""
        while True:
            password = getpass.getpass('Senha: ')
            password2 = getpass.getpass('Repita a senha: ')

            if password != password2:
                self.stderr.write('As senhas não são iguais.')
                continue

            if not password:
                self.stderr.write('Informe a senha.')
                continue

            return password
