# TraceCart

Mini e-commerce de pedidos, 100% backend (APIs REST), feito para servir de base a exercícios de
observabilidade. Esta é a **Etapa 1**: aplicação, persistência, comunicação entre microsserviços,
injeção de falhas e infraestrutura local com Docker Compose. Observabilidade (OpenTelemetry, Cribl,
métricas, dashboards) e Kubernetes ficam para etapas futuras e **não** estão implementados aqui.

## Arquitetura

```text
                 :8000                          :8001
Client ──HTTP──▶ tracecart-order-service ──HTTP──▶ tracecart-payment-service
                        │  (HTTPX, timeout)               │
                        ▼                                 ▼
                 ┌──────────────── tracecart-postgres (16) ────────────────┐
                 │  tracecart_orders (role tracecart_order)                │
                 │  tracecart_payments (role tracecart_payment)            │
                 └──────────── acessível só pela rede interna ─────────────┘
```

| Serviço | Responsabilidade | Porta interna / host |
|---|---|---|
| `tracecart-order-service` | Clientes, produtos, estoque, pedidos e estados; solicita pagamentos e reconcilia resultados | 8000 / 8000 |
| `tracecart-payment-service` | Recebe, simula e persiste pagamentos (aprova/recusa), com idempotência e injeção de falhas | 8000 / 8001 |
| `tracecart-postgres` | Uma instância PostgreSQL 16 com dois bancos isolados | 5432 / não publicada |

Cada serviço acessa **apenas o próprio banco**: cada banco tem um role dono dedicado e o `CONNECT` é
revogado de `PUBLIC`, então o role do Order Service nem consegue conectar em `tracecart_payments`.

**Stack:** Python 3.13, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2 (async) + psycopg 3,
Alembic, HTTPX, Uvicorn, Docker Compose.

## Estrutura de diretórios

```text
tracecart/
├── services/
│   ├── order-service/
│   │   ├── app/
│   │   │   ├── main.py            # app FastAPI, lifespan (startup/shutdown)
│   │   │   ├── api/               # rotas HTTP + validação de entrada (customers, products, orders, health)
│   │   │   ├── schemas/           # modelos Pydantic de entrada/saída (+ contrato do Payment Service)
│   │   │   ├── services/          # regras de negócio e transações
│   │   │   ├── repositories/      # acesso a dados (SQLAlchemy)
│   │   │   ├── models/            # entidades ORM e enums
│   │   │   ├── clients/           # cliente HTTP do Payment Service
│   │   │   ├── database/          # engine, sessão, readiness do banco
│   │   │   └── core/              # configuração, logging, exceções, validação de CPF
│   │   ├── alembic/ + alembic.ini # migrações
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   └── payment-service/           # mesma organização (sem clients/); services/fault_injector.py
├── infrastructure/postgres/init/01-create-databases.sql   # cria roles e bancos no 1º start
├── scripts/
│   ├── seed.py                    # dados de demonstração
│   ├── load_generator.py          # gerador de tráfego
│   └── requirements.txt           # httpx (dependência dos scripts)
├── compose.yaml
├── .env.example
└── README.md
```

## Pré-requisitos

- Docker com Docker Compose v2 (`docker compose version`)
- Python 3.12+ no host, apenas para rodar os scripts `seed.py` e `load_generator.py`
- Portas 8000 e 8001 livres

## Configuração (.env)

```bash
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
```

O `.env` é lido pelo Docker Compose e repassado aos containers; os serviços carregam e validam tudo
via `pydantic-settings` (por exemplo, taxas fora de `[0, 1]` impedem o serviço de iniciar). As senhas
do `.env.example` são placeholders locais. Troque-as à vontade, **antes** do primeiro `up`, porque o
script de init do Postgres só roda com o volume vazio.

| Grupo | Variáveis |
|---|---|
| Ambiente / logs | `ENVIRONMENT`, `LOG_LEVEL` (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| Banco | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `ORDER_DB_USER`, `ORDER_DB_PASSWORD`, `PAYMENT_DB_USER`, `PAYMENT_DB_PASSWORD` |
| Portas no host | `ORDER_SERVICE_PORT` (8000), `PAYMENT_SERVICE_PORT` (8001) |
| Comunicação | `PAYMENT_SERVICE_URL` (`http://tracecart-payment-service:8000`), `PAYMENT_SERVICE_TIMEOUT_SECONDS` (5) |
| Falhas | ver [Cenários de falha](#cenários-de-falha) |

## Executar com Docker Compose

```bash
docker compose up --build -d
docker compose ps             # os 3 serviços devem ficar "healthy"
```

Não há passos manuais: o Postgres cria roles e bancos no primeiro start, e cada serviço executa
`alembic upgrade head` antes de subir o Uvicorn. A ordem de subida é garantida por health checks
(Postgres → Payment → Order).

## Acessar as APIs

- Order Service, Swagger: http://localhost:8000/docs
- Payment Service, Swagger: http://localhost:8001/docs

| Order Service | |
|---|---|
| `POST /customers`, `GET /customers`, `GET /customers/{id}` | clientes (`GET /customers` lista; usado pelo gerador de tráfego) |
| `POST /products`, `GET /products`, `GET /products/{id}` | produtos e estoque (`?category=BOOKS&active_only=true`) |
| `POST /orders`, `GET /orders`, `GET /orders/{id}` | pedidos (`?status=PAID&customer_id=...`) |
| `POST /orders/{id}/pay`, `POST /orders/{id}/cancel` | pagamento/reconciliação e cancelamento |

| Payment Service | |
|---|---|
| `POST /payments` | processa (201) ou devolve o pagamento já existente do pedido (200) |
| `GET /payments/{id}`, `GET /payments/by-order/{order_id}` | consultas |

Os dois serviços expõem `GET /health/live` (processo vivo, sem dependências) e `GET /health/ready`
(verifica o banco; responde 503 se ele estiver indisponível).

Fluxo completo com curl:

```bash
curl -s -X POST localhost:8000/customers -H 'Content-Type: application/json' \
  -d '{"name":"Ana Souza","email":"ana.souza@example.com","cpf":"529.982.247-25"}'
curl -s -X POST localhost:8000/products -H 'Content-Type: application/json' \
  -d '{"name":"USB-C Cable","category":"ELECTRONICS","price":"39.90","stock_quantity":100}'
curl -s -X POST localhost:8000/orders -H 'Content-Type: application/json' \
  -d '{"customer_id":"<CUSTOMER_ID>","payment_method":"PIX","items":[{"product_id":"<PRODUCT_ID>","quantity":2}]}'
curl -s -X POST localhost:8000/orders/<ORDER_ID>/pay
curl -s localhost:8001/payments/by-order/<ORDER_ID>
```

Valores monetários trafegam como string decimal (`"39.90"`) para não perder precisão.

## Seed

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows (Git Bash): source .venv/Scripts/activate
# Windows (PowerShell): .venv\Scripts\activate
pip install -r scripts/requirements.txt
python scripts/seed.py                       # --base-url http://localhost:8000
```

Cria 10 clientes fictícios (e-mails `@example.com`, CPFs sintéticos com dígitos verificadores
válidos) e 15 produtos das 5 categorias, com estoques variados. Inclui de propósito um produto sem
estoque, dois com estoque baixo e um inativo, para demonstrar as regras. Pode ser executado várias
vezes: o que já existe retorna 409 e é ignorado.

## Gerador de tráfego

```bash
python scripts/load_generator.py --requests 1000 --concurrency 10
python scripts/load_generator.py --requests 200 --concurrency 5 --interval 0.5 --base-url http://localhost:8000
```

Cada *request* é uma jornada de compra com várias chamadas: `GET /products` → `POST /orders` →
`POST /orders/{id}/pay` (ou `/cancel`, 10% por padrão, ajustável com `--cancel-rate`) →
`GET /orders/{id}`. Se o resultado do pagamento ficar desconhecido (502/504), a jornada tenta
reconciliar uma vez. No fim, o script mostra um resumo com contagem por status HTTP, latências
média/p95/máx por operação e o status final dos pedidos. Requer o seed (usa os clientes existentes).

## Cenários de falha

Todas as falhas ficam no Payment Service, vêm **desabilitadas** por padrão, são independentes entre
si e usam taxas entre 0 e 1. Para ativar, edite o `.env` e recrie o serviço:

```bash
# ex.: no .env -> PAYMENT_DECLINE_ENABLED=true e PAYMENT_DECLINE_RATE=0.3
docker compose up -d tracecart-payment-service
docker compose logs tracecart-payment-service | grep "Fault injection"   # confirma a configuração ativa
```

| Cenário | Variáveis | Efeito observável |
|---|---|---|
| Pagamento recusado | `PAYMENT_DECLINE_ENABLED`, `PAYMENT_DECLINE_RATE` | Pagamento `DECLINED` com `failure_reason`; pedido `PAYMENT_FAILED` e estoque liberado |
| Latência artificial | `PAYMENT_LATENCY_ENABLED`, `PAYMENT_LATENCY_MIN_MS`, `PAYMENT_LATENCY_MAX_MS` | `asyncio.sleep` antes de finalizar. Acima de `PAYMENT_SERVICE_TIMEOUT_SECONDS` (ex.: 6000–8000 ms) provoca timeout |
| Falha intermitente de banco | `DATABASE_FAILURE_ENABLED`, `DATABASE_FAILURE_RATE` | Payment responde 503; a transação sofre rollback, nada é apagado ou corrompido |
| Timeout HTTP | `PAYMENT_SERVICE_TIMEOUT_SECONDS` (Order Service) | `POST /orders/{id}/pay` responde **504**; o pedido fica em `PAYMENT_PROCESSING` |
| Erro inesperado | `UNEXPECTED_ERROR_ENABLED`, `UNEXPECTED_ERROR_RATE` | Payment responde 500 `{"detail":"Internal server error"}`, sem stack trace; pagamento fica `ERROR` |

Quando o Payment Service falha ou estoura o timeout, o Order Service responde 502/504 e **não**
assume recusa: o pedido continua em `PAYMENT_PROCESSING`, porque o resultado é desconhecido. Para
reconciliar, chame `POST /orders/{id}/pay` de novo. O Order Service consulta
`GET /payments/by-order/{id}`, aplica o resultado se ele já for final ou, caso contrário, reenvia a
solicitação (que é idempotente). Enquanto o pagamento estiver em andamento, o cancelamento é
bloqueado (409).

Exemplo de incidente de timeout (Linux, macOS e Git Bash; no PowerShell use `$env:VAR='valor'`). Variáveis de
ambiente do shell têm precedência sobre o `.env`:

```bash
PAYMENT_LATENCY_ENABLED=true PAYMENT_LATENCY_MIN_MS=6000 PAYMENT_LATENCY_MAX_MS=8000 \
  docker compose up -d tracecart-payment-service
python scripts/load_generator.py --requests 50 --concurrency 5
docker compose up -d tracecart-payment-service          # volta aos valores do .env
```

## Logs

Os serviços usam apenas o módulo `logging` padrão, com saída em stdout e nível definido por
`LOG_LEVEL`. São registrados início e encerramento, operações de negócio, exceções e cada falha
simulada (nível WARNING, prefixo `Simulated fault:`).

```bash
docker compose logs -f                                   # todos
docker compose logs -f tracecart-order-service
docker compose logs --since 10m tracecart-payment-service
```

## Parar e recriar o ambiente

```bash
docker compose stop                # para, mantendo containers e dados
docker compose down                # remove containers e rede; mantém o volume do Postgres
docker compose down -v             # remove também o volume (apaga os dados)
docker compose up --build -d       # recria; com volume novo, bancos e tabelas são recriados
```

Para acessar o banco localmente (o Postgres não é publicado no host):
`docker compose exec tracecart-postgres psql -U postgres -d tracecart_orders`.
No Git Bash (mintty), a sessão interativa precisa do prefixo `winpty`:
`winpty docker compose exec tracecart-postgres psql -U postgres -d tracecart_orders`.
Para consultas pontuais não é preciso: `echo "SELECT 1;" | docker compose exec -T tracecart-postgres psql -U postgres -d tracecart_orders`.

## Decisões arquiteturais

- **Reserva de estoque na criação do pedido.** `POST /orders` trava as linhas dos produtos com
  `SELECT ... FOR UPDATE`, sempre em ordem de id para evitar deadlock, valida e decrementa o estoque
  na mesma transação. Além disso, um `CHECK (stock_quantity >= 0)` no banco funciona como última
  barreira contra venda além do estoque. O estoque continua retido em `PENDING`,
  `PAYMENT_PROCESSING` e `PAID`, e é devolvido **uma única vez**, na transição para
  `PAYMENT_FAILED` ou para `CANCELLED` (a partir de `PENDING`). Como a transição acontece sob lock
  da linha do pedido, não há devolução nem baixa duplicada.
- **Máquina de estados do pedido.** `PENDING → PAYMENT_PROCESSING → PAID | PAYMENT_FAILED`, e
  `PENDING | PAYMENT_FAILED → CANCELLED`. Pedido pago não pode ser cancelado e pedido cancelado não
  pode ser pago. `PAYMENT_FAILED` é terminal para pagamento: o cliente cria outro pedido.
- **Nenhuma transação aberta durante chamadas HTTP.** O pagamento usa duas transações curtas: marca
  `PAYMENT_PROCESSING`, chama o Payment Service e depois aplica o resultado. Não há transação
  distribuída. A consistência vem do estado intermediário somado à reconciliação.
- **Idempotência no Payment Service.** `order_id` é único e funciona como chave de idempotência
  (`INSERT ... ON CONFLICT DO NOTHING`). Um pagamento final é devolvido como está (HTTP 200); um
  pagamento `PROCESSING`/`ERROR` é reprocessado. A finalização usa
  `UPDATE ... WHERE status = 'PROCESSING'`, então em requisições concorrentes vence a primeira.
  Reenvio com valor ou método diferente recebe 409.
- **Timeout ≠ recusa.** Erros de comunicação viram 502/504 com o pedido em `PAYMENT_PROCESSING`;
  só `DECLINED` explícito leva a `PAYMENT_FAILED`.
- **Pronto para várias réplicas e para Kubernetes.** Não há estado em memória: tudo crítico está no
  PostgreSQL. As migrações usam advisory lock, então réplicas podem subir juntas. Configuração e
  URLs vêm de variáveis de ambiente (sem IPs fixos nem segredos no código), os health checks são
  separados em liveness e readiness, e o Uvicorn roda como PID 1, encerrando de forma graciosa
  (`--timeout-graceful-shutdown`) ao receber SIGTERM.
- **Readiness não depende do Payment Service.** Uma falha do Payment Service não deve tirar o Order
  Service de rotação, já que consultas, cadastros e pedidos continuam funcionando; apenas o
  pagamento degrada, com 502/504.
- **Serviços independentes.** Cada serviço tem código, dependências, migrações e imagem próprios.
  A pequena duplicação de utilitários (logging, config) é intencional, para não acoplar os serviços.
- **CPF** é validado (formato e dígitos verificadores) e armazenado normalizado com 11 dígitos. Os
  dados de teste usam apenas CPFs sintéticos. O mascaramento fica para a etapa com Cribl Stream.
