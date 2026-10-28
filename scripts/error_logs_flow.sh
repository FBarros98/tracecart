#!/usr/bin/env bash
# Gera logs WARNING/ERROR nos dois serviços para testar a chegada ao Datadog.
# Ativa cada falha injetada do Payment Service (recria o container), faz 1 pedido + pagamento por
# cenário e, ao sair, restaura o Payment Service com os valores do .env.
# Uso: bash scripts/error_logs_flow.sh [cenario ...]
#   cenarios: client decline db unexpected timeout   (padrão: todos)
set -euo pipefail

ORDER_URL="${ORDER_URL:-http://localhost:8000}"
PAYMENT_URL="${PAYMENT_URL:-http://localhost:8001}"
SCENARIOS=("$@")
[[ ${#SCENARIOS[@]} -gt 0 ]] || SCENARIOS=(client decline db unexpected timeout)
STAMP="$(date +%s)"
CARD="4111 1111 1111 1111"

first_id() { grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4; }

# request <METHOD> <path> [json] -> imprime "<http_code> <corpo>"
request() {
  local method="$1" path="$2" body="${3:-}" out
  if [[ -n "$body" ]]; then
    out="$(curl -sS -m 30 -w '\n%{http_code}' -X "$method" "$ORDER_URL$path" -H 'Content-Type: application/json' -d "$body")"
  else
    out="$(curl -sS -m 30 -w '\n%{http_code}' -X "$method" "$ORDER_URL$path")"
  fi
  echo "${out##*$'\n'} ${out%$'\n'*}"
}

restore() {
  echo
  echo "==> Restaurando Payment Service com os valores do .env"
  docker compose up -d tracecart-payment-service >/dev/null 2>&1 || true
}
trap restore EXIT

wait_payment_ready() {
  local i
  for i in $(seq 1 40); do
    [[ "$(curl -s -o /dev/null -w '%{http_code}' "$PAYMENT_URL/health/ready" || true)" == "200" ]] && return 0
    sleep 1
  done
  echo "Payment Service não ficou pronto a tempo" >&2
  return 1
}

# Recria o Payment Service com as variáveis passadas (têm precedência sobre o .env).
PAYMENT_LOG_BUFFER="$(mktemp)"

# Recriar o container descarta os logs dele; guarda os WARNING/ERROR antes de cada recriação.
snapshot_payment_logs() {
  docker compose logs --since 5m tracecart-payment-service 2>&1 | grep -E " (WARNING|ERROR) " >>"$PAYMENT_LOG_BUFFER" || true
}

apply_faults() {
  snapshot_payment_logs
  env "$@" docker compose up -d tracecart-payment-service >/dev/null 2>&1
  wait_payment_ready
}

echo "==> Preparando cliente e produto"
CUSTOMER="$(request POST /customers "{\"name\":\"Erro Teste $STAMP\",\"email\":\"erro.$STAMP@example.com\",\"cpf\":\"52998224725\"}")"
if [[ "${CUSTOMER%% *}" != "201" ]]; then
  # CPF fixo já usado em outra execução: reaproveita um cliente existente.
  CUSTOMER="200 $(curl -sS "$ORDER_URL/customers?limit=1")"
fi
CUSTOMER_ID="$(echo "${CUSTOMER#* }" | first_id)"
PRODUCT="$(request POST /products "{\"name\":\"Erro Produto $STAMP\",\"category\":\"BOOKS\",\"price\":\"19.90\",\"stock_quantity\":50}")"
PRODUCT_ID="$(echo "${PRODUCT#* }" | first_id)"
[[ -n "$CUSTOMER_ID" && -n "$PRODUCT_ID" ]] || { echo "Falha no preparo: $CUSTOMER / $PRODUCT"; exit 1; }
echo "    customer_id=$CUSTOMER_ID product_id=$PRODUCT_ID"

new_order() {
  local res
  res="$(request POST /orders "{\"customer_id\":\"$CUSTOMER_ID\",\"payment_method\":\"CREDIT_CARD\",\"items\":[{\"product_id\":\"$PRODUCT_ID\",\"quantity\":1}]}")"
  echo "${res#* }" | first_id
}

pay_scenario() { # pay_scenario <descrição> <resultado esperado>
  local order_id res
  order_id="$(new_order)"
  res="$(request POST "/orders/$order_id/pay" "{\"card_number\":\"$CARD\"}")"
  echo "    order_id=$order_id -> HTTP ${res%% *} (esperado: $2)"
  echo "    ${res#* }" | cut -c1-200
}

for scenario in "${SCENARIOS[@]}"; do
  echo
  case "$scenario" in
    client)
      echo "==> [client] Erros do cliente (422/404/409) — aparecem só nos access logs"
      request POST /customers '{"name":"X","email":"invalido","cpf":"123"}' | cut -c1-120
      request GET /orders/00000000-0000-0000-0000-000000000000 | cut -c1-120
      order_id="$(new_order)"
      request POST "/orders/$order_id/pay" '{"card_number":"4111 1111 1111 1112"}' | cut -c1-120
      request POST "/orders/$order_id/cancel" >/dev/null
      request POST "/orders/$order_id/cancel" | cut -c1-120
      ;;
    decline)
      echo "==> [decline] Pagamento recusado (WARNING 'Simulated fault: payment declined')"
      apply_faults PAYMENT_DECLINE_ENABLED=true PAYMENT_DECLINE_RATE=1.0
      pay_scenario decline "200, pedido PAYMENT_FAILED"
      ;;
    db)
      echo "==> [db] Falha de banco (WARNING 'Simulated fault: database failure' + 502 no Order Service)"
      apply_faults DATABASE_FAILURE_ENABLED=true DATABASE_FAILURE_RATE=1.0
      pay_scenario db "502"
      ;;
    unexpected)
      echo "==> [unexpected] Erro inesperado (ERROR 'Unhandled ...' + traceback no Payment; 502 no Order)"
      apply_faults UNEXPECTED_ERROR_ENABLED=true UNEXPECTED_ERROR_RATE=1.0
      pay_scenario unexpected "502"
      ;;
    timeout)
      echo "==> [timeout] Latência acima do timeout (WARNING 'Payment outcome unknown' + 504; leva ~5s)"
      apply_faults PAYMENT_LATENCY_ENABLED=true PAYMENT_LATENCY_MIN_MS=8000 PAYMENT_LATENCY_MAX_MS=8000
      pay_scenario timeout "504"
      ;;
    *)
      echo "Cenário desconhecido: $scenario (use: client decline db unexpected timeout)" >&2
      exit 1
      ;;
  esac
done

echo
echo "==> WARNING/ERROR gerados (últimos 5 min)"
echo "--- tracecart-order-service"
docker compose logs --since 5m tracecart-order-service 2>&1 | grep -E " (WARNING|ERROR) " | cut -c1-260 || true
echo "--- tracecart-payment-service"
snapshot_payment_logs
sort -u "$PAYMENT_LOG_BUFFER" | cut -c1-260
rm -f "$PAYMENT_LOG_BUFFER"
