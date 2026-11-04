#!/usr/bin/env bash
# Roda na EC2, chamado pelo workflow deploy.yml; à mão: bash scripts/deploy.sh (publica a origin/main).
set -euo pipefail

APP_DIR="${APP_DIR:-/home/trustimovel-api}"
GIT_SHA="${GIT_SHA:-origin/main}"
SERVICE="trustimovel-api"
SOCKET="/run/${SERVICE}/gunicorn.sock"

cd "$APP_DIR"

echo "== Código"
git fetch --prune origin
# .env, venv e static não estão no git, então o reset não os toca.
git reset --hard "$GIT_SHA"
git log -1 --format='%h %ci %s'

echo "== Dependências"
venv/bin/pip install --quiet --requirement requirements.txt

echo "== Migrations e arquivos estáticos"
venv/bin/python manage.py migrate --noinput
venv/bin/python manage.py collectstatic --noinput

echo "== Reinicia o serviço"
sudo systemctl restart "$SERVICE"
sleep 3

if ! systemctl is-active --quiet "$SERVICE"; then
    echo "O serviço $SERVICE não subiu."
    sudo journalctl -u "$SERVICE" -n 50 --no-pager
    exit 1
fi

echo "== Verificação"
# Sem token a listagem responde 401: prova que o Django subiu e falou com o banco de permissões.
status=$(curl -s -o /dev/null -w '%{http_code}' --unix-socket "$SOCKET" http://localhost/properties/)

if [ "$status" != "401" ]; then
    echo "A API respondeu $status em /properties/ (esperado 401)."
    sudo journalctl -u "$SERVICE" -n 50 --no-pager
    exit 1
fi

echo "Deploy concluído: $(git rev-parse --short HEAD)"
