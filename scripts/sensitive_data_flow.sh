#!/usr/bin/env bash
# Fluxo completo para gerar logs com CPF (order-service) e cartão (payment-service).
# Cria 1 cliente (CPF sintético válido e novo a cada execução), 1 produto, 1 pedido CREDIT_CARD e o paga.
# Uso: bash scripts/sensitive_data_flow.sh [CARTAO]   (padrão: 4111 1111 1111 1111)
set -euo pipefail

ORDER_URL="${ORDER_URL:-http://localhost:8000}"
CARD="${1:-4111 1111 1111 1111}"
STAMP="$(date +%s)"

# Dígito verificador de CPF: recebe os dígitos já calculados e imprime o próximo.
cpf_digit() {
  local digits="$1" weight=$(( ${#1} + 1 )) total=0 i
  for ((i = 0; i < ${#digits}; i++)); do
    total=$(( total + ${digits:i:1} * (weight - i) ))
  done
  local rem=$(( (total * 10) % 11 ))
  echo $(( rem == 10 ? 0 : rem ))
}

generate_cpf() {
  local base d1 d2
  base="$(printf '%09d' $(( (RANDOM * 32768 + RANDOM) % 1000000000 )))"
  # Evita sequências repetidas (ex. 111111111), recusadas pela validação.
  [[ "$base" =~ ^(.)\1{8}$ ]] && base="123456789"
  d1="$(cpf_digit "$base")"
  d2="$(cpf_digit "$base$d1")"
  echo "$base$d1$d2"
}

# Extrai o primeiro "id" de uma resposta JSON compacta (sem depender de jq).
first_id() { grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4; }

post() { # post <path> <json>
  curl -sS -X POST "$ORDER_URL$1" -H 'Content-Type: application/json' -d "$2"
}

CPF="$(generate_cpf)"
echo "==> Criando cliente (CPF $CPF)"
CUSTOMER="$(post /customers "{\"name\":\"Cliente Teste $STAMP\",\"email\":\"teste.$STAMP@example.com\",\"cpf\":\"$CPF\"}")"
CUSTOMER_ID="$(echo "$CUSTOMER" | first_id)"
[[ -n "$CUSTOMER_ID" ]] || { echo "Falha ao criar cliente: $CUSTOMER"; exit 1; }
echo "    customer_id=$CUSTOMER_ID"

echo "==> Criando produto"
PRODUCT="$(post /products "{\"name\":\"Produto Teste $STAMP\",\"category\":\"BOOKS\",\"price\":\"59.90\",\"stock_quantity\":10}")"
PRODUCT_ID="$(echo "$PRODUCT" | first_id)"
[[ -n "$PRODUCT_ID" ]] || { echo "Falha ao criar produto: $PRODUCT"; exit 1; }
echo "    product_id=$PRODUCT_ID"

echo "==> Criando pedido CREDIT_CARD"
ORDER="$(post /orders "{\"customer_id\":\"$CUSTOMER_ID\",\"payment_method\":\"CREDIT_CARD\",\"items\":[{\"product_id\":\"$PRODUCT_ID\",\"quantity\":1}]}")"
ORDER_ID="$(echo "$ORDER" | first_id)"
[[ -n "$ORDER_ID" ]] || { echo "Falha ao criar pedido: $ORDER"; exit 1; }
echo "    order_id=$ORDER_ID"

echo "==> Pagando com cartão '$CARD'"
PAYMENT="$(post "/orders/$ORDER_ID/pay" "{\"card_number\":\"$CARD\"}")"
echo "    $PAYMENT"

if command -v docker >/dev/null 2>&1; then
  echo
  echo "==> Logs gerados"
  docker compose logs --since 2m tracecart-order-service | grep "Customer created.*$CUSTOMER_ID" || true
  docker compose logs --since 2m tracecart-payment-service | grep "Payment processed.*$ORDER_ID" || true
fi
