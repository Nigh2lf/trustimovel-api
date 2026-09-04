# Boilerplate API Django

Projeto reduzido a um ponto de partida limpo: apenas o model `User` e o fluxo de login (JWT), para recomeçar o desenvolvimento a partir daqui.

## O que existe no projeto

- **`core.User`** (`core/models.py`) — usuário customizado com login por email/senha, `type` (`ADMIN`/`USER`), soft delete e campos de recuperação de senha.
- **Login (JWT)** — `POST /auth-user/` (obtém `access`/`refresh`) e `POST /token-refresh/`.
- **`/users/`** (`UserViewSet`) — CRUD do usuário autenticado, mais as ações:
  - `GET /users/profile/` — dados do usuário logado.
  - `POST /users/forgot-password/` — envia e-mail de recuperação de senha.
  - `POST /users/change-password-forgot-password/` — troca a senha usando o hash recebido por e-mail.
- **Django Admin** (`/admin/`) — cadastro de `User`.
- **Swagger/Redoc** (`/swagger/`, `/redoc/`) — documentação da API.
- **`core/classes/base_viewset.py`** — `BaseViewSet`, um `ModelViewSet` com resposta JSON padronizada (`success`/`status`/`message`/`data`/`error`), transações atômicas em escrita e soft delete via `perform_destroy`.
- **`core/classes/permission_type_user.py`** — `AllPermissionClass`, `AdminPermissionClass`, `UserPermissionClass`, permissões baseadas no campo `User.type`.

## Comandos personalizados

### `createuser` — Criar usuário

```bash
python manage.py createuser
```

O comando solicita interativamente **email** e **password** (com confirmação). Opções:

- `--email EMAIL` / `--password PASSWORD`: define os valores sem prompt.
- `--no-input`: modo não interativo (falha se email/senha não forem passados).
- `--no-validate`: pula a validação de força de senha.

## Instalação

1. Clone o repositório.
2. Crie um ambiente virtual: `python -m venv venv`.
3. Ative o ambiente: `source venv/bin/activate` (Linux/Mac) ou `venv\Scripts\activate` (Windows).
4. Instale as dependências: `pip install -r requirements.txt`.
5. Copie `.env.example` para `.env` e preencha as variáveis (banco de dados, e opcionalmente AWS S3 e envio de e-mail).
6. Execute as migrações: `python manage.py migrate`.
7. Crie um usuário: `python manage.py createuser`.
8. Rode o servidor: `python manage.py runserver`.

## Estrutura do projeto

```
.
├── config/                  # Settings, urls, wsgi/asgi
├── core/                    # App principal
│   ├── classes/             # BaseViewSet e classes de permissão
│   ├── management/commands/ # createuser
│   ├── migrations/
│   ├── serializers/         # UserSerializer + serializers de autenticação
│   ├── services/            # Envio de e-mail (recuperação de senha)
│   ├── template_emails/     # Template do e-mail de recuperação de senha
│   ├── views/                # ViewTokenObtainPair (login) + UserViewSet
│   ├── admin.py
│   └── models.py             # User
├── manage.py
└── requirements.txt
```
