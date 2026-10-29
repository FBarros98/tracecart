"""Mixed traffic for the "slow fraud check on high-value orders" failure scenario.

Covers every Order Service flow plus the Payment Service read endpoints, with orders spread across
the value bands (low < 300, mid 300-999.99, high >= 1000), and reports the outcome per band.
Creates its own customers and products. Payments that end unknown (502/504) are not retried unless
--reconcile-after is given.

Usage:
    python scripts/failure_scenario.py [--duration 300] [--concurrency 4] [--interval 1.0]
        [--mix low=50,mid=30,high=20] [--reconcile-after SECONDS] [--settle 15]
        [--base-url http://localhost:8000] [--payment-url http://localhost:8001]
"""

import argparse
import asyncio
import random
import statistics
import sys
import time
import uuid
from collections import Counter, defaultdict
from decimal import Decimal

import httpx

PAYMENT_METHODS = ("PIX", "CREDIT_CARD", "BOLETO")
CATEGORIES = ("ELECTRONICS", "BOOKS", "CLOTHING", "HOME", "FOOD")
# Public test card numbers.
TEST_CARD_NUMBERS = ("4111111111111111", "5555555555554444", "4242424242424242")
OUTCOME_UNKNOWN_CODES = {202, 502, 504}

MID_VALUE_THRESHOLD = Decimal("300.00")  # same as order-service core/telemetry.py
HIGH_VALUE_THRESHOLD = Decimal("1000.00")
BANDS = ("low", "mid", "high")

# (label, category, price)
BASE_PRODUCTS = [
    ("Cabo USB", "ELECTRONICS", "39.90"),
    ("Camiseta", "CLOTHING", "59.90"),
    ("Cafe Especial", "FOOD", "79.90"),
    ("Livro Tecnico", "BOOKS", "149.90"),
    ("Cafeteira", "HOME", "259.90"),
    ("Teclado Mecanico", "ELECTRONICS", "349.90"),
    ("Tenis de Corrida", "CLOTHING", "429.90"),
    ("Fone com Cancelamento", "ELECTRONICS", "899.00"),
    ("Monitor 27", "ELECTRONICS", "1499.00"),
    ("Notebook", "ELECTRONICS", "4299.00"),
]
STOCK = 100_000
MAX_POOL = 60


def band_of(amount: Decimal) -> str:
    if amount >= HIGH_VALUE_THRESHOLD:
        return "high"
    if amount >= MID_VALUE_THRESHOLD:
        return "mid"
    return "low"


def _check_digit(digits: str) -> str:
    weight = len(digits) + 1
    remainder = (sum(int(d) * (weight - i) for i, d in enumerate(digits)) * 10) % 11
    return "0" if remainder == 10 else str(remainder)


def synthetic_cpf() -> str:
    while True:
        base = "".join(str(random.randint(0, 9)) for _ in range(9))
        if base != base[0] * 9:
            break
    first = _check_digit(base)
    second = _check_digit(base + first)
    digits = base + first + second
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


class Stats:
    def __init__(self) -> None:
        self.calls: Counter[tuple[str, int | str]] = Counter()
        self.latencies: defaultdict[str, list[float]] = defaultdict(list)
        self.outcomes: Counter[str] = Counter()
        self.band_results: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.band_pay_ms: defaultdict[str, list[float]] = defaultdict(list)
        self.band_orders: Counter[str] = Counter()
        self.unknown_orders: dict[str, tuple[str, str]] = {}  # order_id -> (band, payment_method)

    def record(self, operation: str, status: int | str, elapsed: float) -> None:
        self.calls[(operation, status)] += 1
        self.latencies[operation].append(elapsed * 1000)


class Catalog:

    def __init__(self) -> None:
        self.customers: list[str] = []
        self.products: list[dict] = []  # {"id": str, "price": Decimal}


async def call(
    client: httpx.AsyncClient, stats: Stats, operation: str, method: str, url: str, **kwargs
) -> httpx.Response | None:
    started = time.perf_counter()
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        stats.record(operation, type(exc).__name__, time.perf_counter() - started)
        return None
    stats.record(operation, response.status_code, time.perf_counter() - started)
    return response


async def create_customer(client: httpx.AsyncClient, stats: Stats, catalog: Catalog) -> None:
    tag = uuid.uuid4().hex[:10]
    payload = {"name": f"Cliente Cenario {tag}", "email": f"cenario.{tag}@example.com", "cpf": synthetic_cpf()}
    response = await call(client, stats, "create_customer", "POST", "/customers", json=payload)
    if response is not None and response.status_code == 201:
        catalog.customers.append(response.json()["id"])
        if random.random() < 0.3:
            await call(client, stats, "get_customer", "GET", f"/customers/{catalog.customers[-1]}")


async def create_product(
    client: httpx.AsyncClient, stats: Stats, catalog: Catalog, label: str, category: str, price: str
) -> None:
    payload = {
        "name": f"{label} {uuid.uuid4().hex[:6]}",
        "category": category,
        "price": price,
        "stock_quantity": STOCK,
    }
    response = await call(client, stats, "create_product", "POST", "/products", json=payload)
    if response is not None and response.status_code == 201:
        product = {"id": response.json()["id"], "price": Decimal(price)}
        if len(catalog.products) >= MAX_POOL:
            catalog.products.pop(random.randrange(len(BASE_PRODUCTS), len(catalog.products)))
        catalog.products.append(product)
        if random.random() < 0.3:
            await call(client, stats, "get_product", "GET", f"/products/{product['id']}")


def build_items(catalog: Catalog, target: str) -> tuple[list[dict], Decimal] | None:
    """Random basket whose total lands in the target band (rejection sampling)."""
    for _ in range(30):
        chosen = random.sample(catalog.products, k=min(len(catalog.products), random.randint(1, 3)))
        items = [{"product_id": p["id"], "quantity": random.randint(1, 4)} for p in chosen]
        total = sum(p["price"] * i["quantity"] for p, i in zip(chosen, items))
        if band_of(total) == target:
            return items, total
    return None


async def probe_reads(client: httpx.AsyncClient, stats: Stats, catalog: Catalog) -> None:
    roll = random.random()
    if roll < 0.2:
        await call(client, stats, "list_customers", "GET", "/customers", params={"limit": 20})
    elif roll < 0.4:
        params = {"limit": 20}
        if random.random() < 0.5:
            params["category"] = random.choice(CATEGORIES)
        await call(client, stats, "list_products", "GET", "/products", params=params)
    elif roll < 0.6:
        params = {"limit": 20, "status": random.choice(["PENDING", "PAYMENT_PROCESSING", "PAID", "CANCELLED"])}
        await call(client, stats, "list_orders", "GET", "/orders", params=params)
    elif roll < 0.7 and catalog.customers:
        await call(
            client, stats, "list_orders_by_customer", "GET", "/orders",
            params={"customer_id": random.choice(catalog.customers)},
        )
    elif roll < 0.8:
        await call(client, stats, "get_order_not_found", "GET", f"/orders/{uuid.uuid4()}")
    elif roll < 0.9:
        bad = {"name": "Invalido", "email": "invalido@example.com", "cpf": "111.111.111-11"}
        await call(client, stats, "create_customer_invalid", "POST", "/customers", json=bad)
    else:
        await call(client, stats, "pay_order_not_found", "POST", f"/orders/{uuid.uuid4()}/pay")


async def journey(
    client: httpx.AsyncClient, payment_client: httpx.AsyncClient, stats: Stats, catalog: Catalog,
    weights: list[int], cancel_rate: float, reconcile_after: float | None,
) -> None:
    if random.random() < 0.25 or not catalog.customers:
        await create_customer(client, stats, catalog)
    if random.random() < 0.2:
        label, category = random.choice(["Gadget", "Acessorio", "Item Premium"]), random.choice(CATEGORIES)
        price = f"{random.uniform(15, 2500):.2f}"
        await create_product(client, stats, catalog, label, category, price)
    if random.random() < 0.3:
        await probe_reads(client, stats, catalog)
    if not catalog.customers or not catalog.products:
        stats.outcomes["catalog_empty"] += 1
        return

    target = random.choices(BANDS, weights=weights)[0]
    basket = build_items(catalog, target)
    if basket is None:
        stats.outcomes["no_basket_for_band"] += 1
        return
    items, total = basket
    method = random.choice(PAYMENT_METHODS)
    payload = {"customer_id": random.choice(catalog.customers), "payment_method": method, "items": items}
    response = await call(client, stats, "create_order", "POST", "/orders", json=payload)
    if response is None or response.status_code != 201:
        code = response.status_code if response is not None else "error"
        stats.outcomes[f"order_failed_{code}"] += 1
        return
    order_id = response.json()["id"]
    stats.band_orders[target] += 1

    if random.random() < cancel_rate:
        response = await call(client, stats, "cancel_order", "POST", f"/orders/{order_id}/cancel")
        stats.outcomes["CANCELLED" if response is not None and response.status_code == 200 else "cancel_failed"] += 1
        await call(client, stats, "pay_cancelled_order", "POST", f"/orders/{order_id}/pay")
        return

    pay_kwargs = {"json": {"card_number": random.choice(TEST_CARD_NUMBERS)}} if method == "CREDIT_CARD" else {}
    started = time.perf_counter()
    response = await call(client, stats, "pay_order", "POST", f"/orders/{order_id}/pay", **pay_kwargs)
    stats.band_pay_ms[target].append((time.perf_counter() - started) * 1000)
    code = response.status_code if response is not None else "error"
    stats.band_results[target][str(code)] += 1

    if code in OUTCOME_UNKNOWN_CODES or code == "error":
        stats.unknown_orders[order_id] = (target, method)
        if reconcile_after is not None:
            await asyncio.sleep(reconcile_after)
            response = await call(client, stats, "reconcile_payment", "POST", f"/orders/{order_id}/pay", **pay_kwargs)
            if response is not None and response.status_code == 200:
                stats.unknown_orders.pop(order_id, None)
                stats.band_results[target]["reconciled"] += 1
    elif code == 200:
        if random.random() < 0.15:
            await call(client, stats, "pay_order_again", "POST", f"/orders/{order_id}/pay", **pay_kwargs)
        if random.random() < 0.5:
            await call(payment_client, stats, "payment_by_order", "GET", f"/payments/by-order/{order_id}")

    response = await call(client, stats, "get_order", "GET", f"/orders/{order_id}")
    if response is not None and response.status_code == 200:
        stats.outcomes[f"{target}:{response.json()['status']}"] += 1


async def check_divergence(client: httpx.AsyncClient, payment_client: httpx.AsyncClient, stats: Stats) -> Counter:
    """Orders left with an unknown payment outcome vs. what the Payment Service stored."""
    result: Counter[str] = Counter()
    for order_id, (band, _) in stats.unknown_orders.items():
        order = await call(client, stats, "get_order", "GET", f"/orders/{order_id}")
        payment = await call(payment_client, stats, "payment_by_order", "GET", f"/payments/by-order/{order_id}")
        order_status = order.json()["status"] if order is not None and order.status_code == 200 else "?"
        payment_status = payment.json()["status"] if payment is not None and payment.status_code == 200 else "none"
        result[f"{band}: order={order_status} payment={payment_status}"] += 1
    return result


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered)) - 1))]


def print_summary(stats: Stats, journeys: int, elapsed: float, divergence: Counter | None) -> None:
    print("\n=== TraceCart failure scenario summary ===")
    print(f"Journeys: {journeys}   HTTP calls: {sum(stats.calls.values())}   Duration: {elapsed:.1f}s")

    print("\nHTTP calls by operation:")
    print(f"  {'operation':<26}{'count':>7}{'avg ms':>10}{'p95 ms':>10}{'max ms':>10}  status codes")
    for operation, latencies in sorted(stats.latencies.items()):
        codes = ", ".join(f"{c}={n}" for (op, c), n in sorted(stats.calls.items(), key=str) if op == operation)
        print(
            f"  {operation:<26}{len(latencies):>7}{statistics.fmean(latencies):>10.1f}"
            f"{percentile(latencies, 95):>10.1f}{max(latencies):>10.1f}  {codes}"
        )

    print("\nPayments by value band:")
    print(f"  {'band':<6}{'orders':>8}{'pay avg ms':>12}{'pay p95 ms':>12}  results (HTTP status of POST /pay)")
    for band in BANDS:
        times = stats.band_pay_ms[band]
        avg = f"{statistics.fmean(times):.0f}" if times else "-"
        p95 = f"{percentile(times, 95):.0f}" if times else "-"
        results = ", ".join(f"{k}={v}" for k, v in sorted(stats.band_results[band].items())) or "-"
        print(f"  {band:<6}{stats.band_orders[band]:>8}{avg:>12}{p95:>12}  {results}")

    print("\nJourney outcomes (band:final order status, or reason):")
    for outcome, count in sorted(stats.outcomes.items()):
        print(f"  {outcome:<34}{count:>6}")

    if divergence is not None:
        print(f"\nOrders with unknown payment outcome: {len(stats.unknown_orders)}")
        for key, count in sorted(divergence.items()):
            print(f"  {key:<56}{count:>6}")


async def run(args: argparse.Namespace) -> int:
    stats = Stats()
    catalog = Catalog()
    weights = args.weights
    timeout = httpx.Timeout(30.0)  # above the Order Service payment timeout
    limits = httpx.Limits(max_connections=args.concurrency * 3)
    async with (
        httpx.AsyncClient(base_url=args.base_url, timeout=timeout, limits=limits) as client,
        httpx.AsyncClient(base_url=args.payment_url, timeout=timeout, limits=limits) as payment_client,
    ):
        try:
            if (await client.get("/health/ready")).status_code != 200:
                print("Order Service is not ready.", file=sys.stderr)
                return 1
        except httpx.HTTPError as exc:
            print(f"Cannot reach Order Service at {args.base_url}: {exc}", file=sys.stderr)
            return 1

        print("Creating base customers and products...")
        for _ in range(5):
            await create_customer(client, stats, catalog)
        for label, category, price in BASE_PRODUCTS:
            await create_product(client, stats, catalog, label, category, price)
        if not catalog.customers or len(catalog.products) < len(BASE_PRODUCTS):
            print("Could not create the base catalog; is the Order Service healthy?", file=sys.stderr)
            return 1

        journeys = 0
        deadline = time.monotonic() + args.duration

        async def worker() -> None:
            nonlocal journeys
            while time.monotonic() < deadline:
                try:
                    await journey(client, payment_client, stats, catalog, weights, args.cancel_rate, args.reconcile_after)
                except Exception as exc:  # one failed journey must not stop the run
                    stats.outcomes[f"journey_error_{type(exc).__name__}"] += 1
                journeys += 1
                await asyncio.sleep(args.interval * random.uniform(0.5, 1.5))

        async def progress() -> None:
            while True:
                await asyncio.sleep(30)
                print(f"  [{time.strftime('%H:%M:%S')}] journeys={journeys} unknown_outcomes={len(stats.unknown_orders)}")

        print(f"Running for {args.duration}s (concurrency={args.concurrency}, mix={args.mix}). Ctrl+C to stop.")
        started = time.perf_counter()
        ticker = asyncio.create_task(progress())
        divergence = None
        try:
            await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        finally:
            ticker.cancel()
        if stats.unknown_orders:
            print(f"Waiting {args.settle}s for the Payment Service to finish in-flight payments...")
            await asyncio.sleep(args.settle)
            divergence = await check_divergence(client, payment_client, stats)
        print_summary(stats, journeys, max(time.perf_counter() - started, 0.001), divergence)
    return 0


def parse_mix(text: str) -> list[int]:
    try:
        parts = dict(item.split("=") for item in text.split(","))
        weights = [int(parts[band]) for band in BANDS]
    except (ValueError, KeyError):
        raise argparse.ArgumentTypeError("use low=50,mid=30,high=20") from None
    if min(weights) < 0 or sum(weights) == 0:
        raise argparse.ArgumentTypeError("weights must be >= 0 and not all zero")
    return weights


def main() -> int:
    parser = argparse.ArgumentParser(description="Mixed-value traffic for the slow fraud-check scenario")
    parser.add_argument("--duration", type=int, default=300, help="seconds of traffic")
    parser.add_argument("--concurrency", type=int, default=4, help="journeys in parallel")
    parser.add_argument("--interval", type=float, default=1.0, help="pause (s) after each journey per worker")
    parser.add_argument("--mix", default="low=50,mid=30,high=20", help="journey share per value band")
    parser.add_argument("--cancel-rate", type=float, default=0.1, help="share of orders cancelled instead of paid")
    parser.add_argument("--reconcile-after", type=float, default=None,
                        help="retry payments with unknown outcome after N seconds (default: never)")
    parser.add_argument("--settle", type=int, default=15,
                        help="seconds to wait before comparing stuck orders with the Payment Service")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Order Service base URL")
    parser.add_argument("--payment-url", default="http://localhost:8001", help="Payment Service base URL")
    args = parser.parse_args()
    try:
        args.weights = parse_mix(args.mix)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.duration < 1 or args.concurrency < 1 or args.interval < 0 or not 0 <= args.cancel_rate <= 1:
        parser.error("--duration/--concurrency must be >= 1, --interval >= 0, --cancel-rate in [0, 1]")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
