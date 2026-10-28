"""Traffic generator for TraceCart (HTTPX + asyncio).

Each "request" is one shopping journey made of several HTTP calls:
    GET /products -> POST /orders -> POST /orders/{id}/pay (or /cancel) -> GET /orders/{id}

When the payment outcome is unknown (HTTP 502/504 or 202), the journey retries the payment once to
exercise reconciliation.

Usage:
    python scripts/load_generator.py --requests 1000 --concurrency 10 [--interval 0.0]
        [--base-url http://localhost:8000] [--cancel-rate 0.1]
"""

import argparse
import asyncio
import random
import statistics
import sys
import time
from collections import Counter, defaultdict

import httpx

PAYMENT_METHODS = ("PIX", "CREDIT_CARD", "BOLETO")
# Public test card numbers (valid Luhn), never real cards.
TEST_CARD_NUMBERS = ("4111111111111111", "5555555555554444", "4242424242424242")
OUTCOME_UNKNOWN_CODES = {202, 502, 504}


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


async def journey(client: httpx.AsyncClient, stats: Stats, customers: list[str], cancel_rate: float) -> None:
    response = await call(client, stats, "list_products", "GET", "/products", params={"active_only": "true"})
    if response is None or response.status_code != 200:
        stats.outcomes["products_unavailable"] += 1
        return
    available = [p for p in response.json() if p["stock_quantity"] > 0]
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
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.interval < 0 or not 0 <= args.cancel_rate <= 1:
        parser.error("--requests/--concurrency must be >= 1, --interval >= 0, --cancel-rate in [0, 1]")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
