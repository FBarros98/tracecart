"""Traffic generator for TraceCart (HTTPX + asyncio).

Each "request" is one shopping journey made of several HTTP calls:
    GET /products -> POST /orders -> POST /orders/{id}/pay (or /cancel) -> GET /orders/{id}

If the payment outcome is unknown (502/504/202), the journey retries it once.

Usage:
    python scripts/load_generator.py --requests 1000 --concurrency 10 [--interval 0.0]
        [--base-url http://localhost:8000] [--cancel-rate 0.1]
    python scripts/load_generator.py --continuous [--concurrency 3] [--interval 2.0]

--continuous runs until Ctrl+C. Since stock is finite, every RESTOCK_INTERVAL_SECONDS it creates a
new version ("<name> #2", "#3", ...) of products running low.
"""

import argparse
import asyncio
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict

import httpx

PAYMENT_METHODS = ("PIX", "CREDIT_CARD", "BOLETO")
# Public test card numbers.
TEST_CARD_NUMBERS = ("4111111111111111", "5555555555554444", "4242424242424242")
OUTCOME_UNKNOWN_CODES = {202, 502, 504}

PRODUCTS_PAGE_SIZE = 100
RESTOCK_INTERVAL_SECONDS = 60
RESTOCK_THRESHOLD = 30
RESTOCK_QUANTITY = 300
PRODUCT_NAME = re.compile(r"^(?P<base>.*?)(?: #(?P<version>\d+))?$")


class Stats:
    def __init__(self) -> None:
        self.calls: Counter[tuple[str, int | str]] = Counter()
        self.latencies: defaultdict[str, list[float]] = defaultdict(list)
        self.outcomes: Counter[str] = Counter()

    def record(self, operation: str, status: int | str, elapsed: float) -> None:
        self.calls[(operation, status)] += 1
        self.latencies[operation].append(elapsed * 1000)


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


async def list_products(client: httpx.AsyncClient, stats: Stats) -> list[dict] | None:
    """All active products, across pages."""
    products: list[dict] = []
    while True:
        response = await call(
            client, stats, "list_products", "GET", "/products",
            params={"active_only": "true", "limit": PRODUCTS_PAGE_SIZE, "offset": len(products)},
        )
        if response is None or response.status_code != 200:
            return None
        page = response.json()
        products.extend(page)
        if len(page) < PRODUCTS_PAGE_SIZE:
            return products


async def restock(client: httpx.AsyncClient, stats: Stats) -> None:
    products = await list_products(client, stats)
    if products is None:
        return
    versions: defaultdict[str, list[dict]] = defaultdict(list)
    for product in products:
        versions[PRODUCT_NAME.match(product["name"])["base"]].append(product)
    for base, group in versions.items():
        if sum(p["stock_quantity"] for p in group) >= RESTOCK_THRESHOLD:
            continue
        latest = max(int(PRODUCT_NAME.match(p["name"])["version"] or 1) for p in group)
        payload = {
            "name": f"{base} #{latest + 1}",
            "category": group[0]["category"],
            "price": group[0]["price"],
            "stock_quantity": RESTOCK_QUANTITY,
        }
        response = await call(client, stats, "restock_product", "POST", "/products", json=payload)
        if response is not None and response.status_code == 201:
            print(f"  restocked: {payload['name']} (stock={RESTOCK_QUANTITY})")


async def journey(client: httpx.AsyncClient, stats: Stats, customers: list[str], cancel_rate: float) -> None:
    products = await list_products(client, stats)
    if products is None:
        stats.outcomes["products_unavailable"] += 1
        return
    available = [p for p in products if p["stock_quantity"] > 0]
    if not available:
        stats.outcomes["no_stock_available"] += 1
        return

    chosen = random.sample(available, k=min(len(available), random.randint(1, 3)))
    payload = {
        "customer_id": random.choice(customers),
        "payment_method": random.choice(PAYMENT_METHODS),
        "items": [
            {"product_id": p["id"], "quantity": random.randint(1, min(3, p["stock_quantity"]))}
            for p in chosen
        ],
    }
    response = await call(client, stats, "create_order", "POST", "/orders", json=payload)
    if response is None or response.status_code != 201:
        code = response.status_code if response is not None else "error"
        stats.outcomes["order_rejected_out_of_stock" if code == 409 else f"order_failed_{code}"] += 1
        return
    order_id = response.json()["id"]

    if random.random() < cancel_rate:
        response = await call(client, stats, "cancel_order", "POST", f"/orders/{order_id}/cancel")
        stats.outcomes["CANCELLED" if response is not None and response.status_code == 200 else "cancel_failed"] += 1
    else:
        pay_kwargs = {}
        if payload["payment_method"] == "CREDIT_CARD":
            pay_kwargs["json"] = {"card_number": random.choice(TEST_CARD_NUMBERS)}
        response = await call(client, stats, "pay_order", "POST", f"/orders/{order_id}/pay", **pay_kwargs)
        if response is not None and response.status_code in OUTCOME_UNKNOWN_CODES:
            await asyncio.sleep(1)
            response = await call(
                client, stats, "reconcile_payment", "POST", f"/orders/{order_id}/pay", **pay_kwargs
            )

    response = await call(client, stats, "get_order", "GET", f"/orders/{order_id}")
    if response is not None and response.status_code == 200:
        status = response.json()["status"]
        if status != "CANCELLED":
            stats.outcomes[status] += 1


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def print_summary(stats: Stats, journeys: int, elapsed: float) -> None:
    total_calls = sum(stats.calls.values())
    print("\n=== TraceCart load generator summary ===")
    print(f"Journeys: {journeys}   HTTP calls: {total_calls}   Duration: {elapsed:.1f}s   "
          f"Throughput: {total_calls / elapsed:.1f} calls/s")

    print("\nHTTP calls by operation:")
    print(f"  {'operation':<20}{'count':>7}{'avg ms':>10}{'p95 ms':>10}{'max ms':>10}  status codes")
    for operation, latencies in sorted(stats.latencies.items()):
        codes = ", ".join(
            f"{code}={count}" for (op, code), count in sorted(stats.calls.items(), key=str) if op == operation
        )
        print(
            f"  {operation:<20}{len(latencies):>7}{statistics.fmean(latencies):>10.1f}"
            f"{percentile(latencies, 95):>10.1f}{max(latencies):>10.1f}  {codes}"
        )

    print("\nJourney outcomes (final order status or reason):")
    for outcome, count in stats.outcomes.most_common():
        print(f"  {outcome:<30}{count:>7}")


async def run_continuous(
    client: httpx.AsyncClient, stats: Stats, customers: list[str], args: argparse.Namespace
) -> int:
    journeys = 0

    async def worker() -> None:
        nonlocal journeys
        while True:
            try:
                await journey(client, stats, customers, args.cancel_rate)
            except Exception as exc:  # one failed journey must not stop the run
                stats.outcomes[f"journey_error_{type(exc).__name__}"] += 1
            journeys += 1
            await asyncio.sleep(args.interval * random.uniform(0.5, 1.5))

    async def maintenance() -> None:
        while True:
            await restock(client, stats)
            print(f"  [{time.strftime('%H:%M:%S')}] journeys={journeys} http_calls={sum(stats.calls.values())}")
            await asyncio.sleep(RESTOCK_INTERVAL_SECONDS)

    print(f"Running continuously against {args.base_url} "
          f"(concurrency={args.concurrency}, interval~{args.interval}s). Ctrl+C to stop.")
    started = time.perf_counter()
    tasks = [asyncio.create_task(worker()) for _ in range(args.concurrency)]
    tasks.append(asyncio.create_task(maintenance()))
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        print_summary(stats, journeys, max(time.perf_counter() - started, 0.001))
    return 0


async def run(args: argparse.Namespace) -> int:
    stats = Stats()
    timeout = httpx.Timeout(30.0)
    limits = httpx.Limits(max_connections=args.concurrency * 2)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout, limits=limits) as client:
        try:
            response = await client.get("/customers", params={"limit": 100})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"Could not load customers from {args.base_url}: {exc}", file=sys.stderr)
            return 1
        customers = [c["id"] for c in response.json()]
        if not customers:
            print("No customers found. Run `python scripts/seed.py` first.", file=sys.stderr)
            return 1

        if args.continuous:
            return await run_continuous(client, stats, customers, args)

        semaphore = asyncio.Semaphore(args.concurrency)
        completed = 0

        async def worker() -> None:
            nonlocal completed
            async with semaphore:
                await journey(client, stats, customers, args.cancel_rate)
                completed += 1
                if completed % max(1, args.requests // 10) == 0:
                    print(f"  progress: {completed}/{args.requests}")
                if args.interval > 0:
                    await asyncio.sleep(args.interval)

        print(f"Running {args.requests} journeys against {args.base_url} "
              f"(concurrency={args.concurrency}, interval={args.interval}s)")
        started = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(args.requests)))
        print_summary(stats, args.requests, time.perf_counter() - started)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate traffic against the TraceCart Order Service")
    parser.add_argument("--requests", type=int, default=100, help="number of shopping journeys")
    parser.add_argument("--concurrency", type=int, default=5, help="journeys executed in parallel")
    parser.add_argument("--interval", type=float, default=0.0, help="pause (s) after each journey per worker")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Order Service base URL")
    parser.add_argument("--cancel-rate", type=float, default=0.1, help="share of orders cancelled instead of paid")
    parser.add_argument("--continuous", action="store_true",
                        help="run until Ctrl+C, ignoring --requests (interval defaults to 2s)")
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.interval < 0 or not 0 <= args.cancel_rate <= 1:
        parser.error("--requests/--concurrency must be >= 1, --interval >= 0, --cancel-rate in [0, 1]")
    if args.continuous and args.interval == 0:
        args.interval = 2.0
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
