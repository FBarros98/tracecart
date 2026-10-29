"""Manual OpenTelemetry helpers (spans and business metrics through the API only; the SDK is
configured by `opentelemetry-instrument`)."""

from decimal import Decimal

from collections.abc import Iterable

from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Observation

tracer = trace.get_tracer("tracecart.order-service")
meter = metrics.get_meter("tracecart.order-service")

# Business metrics. `value_band` (low|mid|high) is the dimension that localizes a degradation;
# `outcome` is approved|declined|timeout (timeout = payment outcome unknown, not a decline).
orders_created = meter.create_counter(
    "orders.created", unit="{order}", description="Orders created, by value band."
)
orders_payments = meter.create_counter(
    "orders.payments",
    unit="{payment}",
    description="Payment attempts finished from the Order Service point of view, by value band and outcome.",
)
orders_revenue = meter.create_counter(
    "orders.revenue", unit="BRL", description="Amount of orders whose payment was approved, by value band."
)

MID_VALUE_THRESHOLD = Decimal("300.00")
HIGH_VALUE_THRESHOLD = Decimal("1000.00")


def value_band(amount: Decimal) -> str:
    """Bucket an order total into a low-cardinality band for span attributes."""
    if amount >= HIGH_VALUE_THRESHOLD:
        return "high"
    if amount >= MID_VALUE_THRESHOLD:
        return "mid"
    return "low"


# `orders.stuck`: orders in PAYMENT_PROCESSING for longer than STUCK_AFTER_SECONDS (outcome still
# unknown, waiting for reconciliation). The gauge callback runs on the SDK's metric reader thread
# and must not touch the event loop, so a background task (services/stuck_orders.py) samples the
# database and stores the counts here.
STUCK_AFTER_SECONDS = 30
STUCK_SAMPLE_INTERVAL_SECONDS = 15
VALUE_BANDS = ("low", "mid", "high")

_stuck_orders: dict[str, int] = dict.fromkeys(VALUE_BANDS, 0)


def set_stuck_orders(counts: dict[str, int]) -> None:
    # Every band is always reported, so the gauge goes back to 0 once the orders are reconciled.
    for band in VALUE_BANDS:
        _stuck_orders[band] = counts.get(band, 0)


def _observe_stuck_orders(options: CallbackOptions) -> Iterable[Observation]:
    for band, count in _stuck_orders.items():
        yield Observation(count, {"value_band": band})


meter.create_observable_gauge(
    "orders.stuck",
    callbacks=[_observe_stuck_orders],
    unit="{order}",
    description=f"Orders in PAYMENT_PROCESSING for more than {STUCK_AFTER_SECONDS}s, by value band.",
)
