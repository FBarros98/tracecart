"""Populate TraceCart with demo customers and products through the public REST API.

Idempotent: existing records answer 409 and are skipped.

Usage:
    python scripts/seed.py [--base-url http://localhost:8000]
"""

import argparse
import random
import sys

import httpx

# CPFs are synthetic.
CUSTOMERS = [
    ("Ana Beatriz Moreira", "ana.moreira@example.com"),
    ("Bruno Henrique Lima", "bruno.lima@example.com"),
    ("Carla Fernandes Rocha", "carla.rocha@example.com"),
    ("Diego Alves Pereira", "diego.pereira@example.com"),
    ("Eduarda Costa Martins", "eduarda.martins@example.com"),
    ("Felipe Souza Ramos", "felipe.ramos@example.com"),
    ("Gabriela Nunes Teixeira", "gabriela.teixeira@example.com"),
    ("Henrique Barbosa Dias", "henrique.dias@example.com"),
    ("Isabela Cardoso Melo", "isabela.melo@example.com"),
    ("João Pedro Azevedo", "joao.azevedo@example.com"),
]

# (name, category, price, stock_quantity, is_active)
PRODUCTS = [
    ("Wireless Mouse", "ELECTRONICS", "89.90", 2000, True),
    ("Mechanical Keyboard", "ELECTRONICS", "349.90", 800, True),
    ("27-inch Monitor", "ELECTRONICS", "1499.00", 150, True),
    ("Noise Cancelling Headphones", "ELECTRONICS", "899.00", 5, True),
    ("Clean Code", "BOOKS", "119.90", 1200, True),
    ("Designing Data-Intensive Applications", "BOOKS", "189.90", 600, True),
    ("The Pragmatic Programmer", "BOOKS", "139.90", 0, True),
    ("Cotton T-Shirt", "CLOTHING", "59.90", 3000, True),
    ("Denim Jacket", "CLOTHING", "279.90", 300, True),
    ("Running Shoes", "CLOTHING", "429.90", 8, True),
    ("Coffee Maker", "HOME", "259.90", 400, True),
    ("Ceramic Dinner Set", "HOME", "349.00", 120, True),
    ("Vintage Desk Lamp", "HOME", "199.90", 50, False),
    ("Specialty Coffee Beans 1kg", "FOOD", "79.90", 2500, True),
    ("Dark Chocolate Box", "FOOD", "49.90", 1500, True),
]


def _check_digit(digits: str) -> str:
    weight = len(digits) + 1
    remainder = (sum(int(d) * (weight - i) for i, d in enumerate(digits)) * 10) % 11
    return "0" if remainder == 10 else str(remainder)


def synthetic_cpf(rng: random.Random) -> str:
    while True:
        base = "".join(str(rng.randint(0, 9)) for _ in range(9))
        if base != base[0] * 9:
            break
    first = _check_digit(base)
    second = _check_digit(base + first)
    digits = base + first + second
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def create(client: httpx.Client, path: str, payload: dict, label: str) -> str:
    response = client.post(path, json=payload)
    if response.status_code == 201:
        print(f"  created  {label}")
        return "created"
    if response.status_code == 409:
        print(f"  exists   {label}")
        return "existing"
    print(f"  FAILED   {label}: HTTP {response.status_code} {response.text}", file=sys.stderr)
    return "failed"


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed TraceCart with demo data")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Order Service base URL")
    args = parser.parse_args()

    rng = random.Random(20261018)
    results: dict[str, int] = {"created": 0, "existing": 0, "failed": 0}

    try:
        with httpx.Client(base_url=args.base_url, timeout=10) as client:
            client.get("/health/ready").raise_for_status()

            print("Customers:")
            for name, email in CUSTOMERS:
                payload = {"name": name, "email": email, "cpf": synthetic_cpf(rng)}
                results[create(client, "/customers", payload, email)] += 1

            print("Products:")
            for name, category, price, stock, active in PRODUCTS:
                payload = {
                    "name": name,
                    "category": category,
                    "price": price,
                    "stock_quantity": stock,
                    "is_active": active,
                }
                results[create(client, "/products", payload, f"{name} [{category}] stock={stock}")] += 1
    except httpx.HTTPError as exc:
        print(f"Could not reach the Order Service at {args.base_url}: {exc}", file=sys.stderr)
        return 1

    print(
        f"\nDone: {results['created']} created, {results['existing']} already existed, "
        f"{results['failed']} failed."
    )
    return 1 if results["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
