#!/usr/bin/env bash
# Roda na Action: manda um script shell para a EC2 pelo Systems Manager e espera o resultado.
# Uso: scripts/ssm-run.sh "comentário" <<'EOF' ...script... EOF   (o script vem pelo stdin)
set -euo pipefail

: "${EC2_INSTANCE_ID:?Defina a variável EC2_INSTANCE_ID no repositório}"
comment="${1:-deploy}"
script=$(cat)

# O script inteiro vai como um único comando; o SSM o grava em arquivo e executa como root.
parameters=$(jq -n --arg script "$script" '{commands: [$script], executionTimeout: ["900"]}')

command_id=$(
    aws ssm send-command \
        --instance-ids "$EC2_INSTANCE_ID" \
        --document-name AWS-RunShellScript \
        --comment "${comment:0:100}" \
        --parameters "$parameters" \
        --query Command.CommandId \
        --output text
)
echo "Comando SSM $command_id enviado para $EC2_INSTANCE_ID"

status=Pending

# Até 15 minutos; logo após o envio a invocação ainda pode não existir, daí o "|| echo Pending".
for _ in $(seq 1 180); do
    sleep 5
    status=$(
        aws ssm get-command-invocation \
            --command-id "$command_id" \
            --instance-id "$EC2_INSTANCE_ID" \
            --query Status \
            --output text 2>/dev/null || echo Pending
    )

    case "$status" in
        Pending | InProgress | Delayed) ;;
        *) break ;;
    esac
done

invocation() {
    aws ssm get-command-invocation \
        --command-id "$command_id" \
        --instance-id "$EC2_INSTANCE_ID" \
        --query "$1" \
        --output text
}

echo "== Saída do servidor"
invocation StandardOutputContent
invocation StandardErrorContent >&2

if [ "$status" != "Success" ]; then
    echo "O comando terminou com status $status."
    exit 1
fi
