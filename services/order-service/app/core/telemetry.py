"""Manual spans and business metrics (API only; the SDK is set up by `opentelemetry-instrument`)."""

from decimal import Decimal

from collections.abc import Iterable

from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Observation

tracer = trace.get_tracer("tracecart.order-service")
meter = metrics.get_meter("tracecart.order-service")

# `outcome` is approved|declined|timeout (timeout = outcome unknown, not a decline).
orders_created = meter.create_counter(
    "tracecart.orders.created", unit="{order}", description="Orders created, by value band."
)
orders_payments = meter.create_counter(
    "tracecart.payments.attempts",
    unit="{payment}",
    description="Payment attempts finished from the Order Service point of view, by value band and outcome.",
)
orders_revenue = meter.create_counter(
    "tracecart.payments.approved_amount", unit="BRL", description="Amount of orders whose payment was approved, by value band."
)

MID_VALUE_THRESHOLD = Decimal("300.00")
HIGH_VALUE_THRESHOLD = Decimal("1000.00")


def value_band(amount: Decimal) -> str:
    if amount >= HIGH_VALUE_THRESHOLD:
        return "high"
    if amount >= MID_VALUE_THRESHOLD:
        return "mid"
    return "low"


# Gauge `tracecart.orders.awaiting_payment_result`. Its callback runs on the SDK's reader thread,
# so services/stuck_orders.py samples the database and stores the counts here.
STUCK_AFTER_SECONDS = 30
STUCK_SAMPLE_INTERVAL_SECONDS = 15
VALUE_BANDS = ("low", "mid", "high")

_stuck_orders: dict[str, int] = dict.fromkeys(VALUE_BANDS, 0)


def set_stuck_orders(counts: dict[str, int]) -> None:
    for band in VALUE_BANDS:
        _stuck_orders[band] = counts.get(band, 0)


def _observe_stuck_orders(options: CallbackOptions) -> Iterable[Observation]:
    for band, count in _stuck_orders.items():
        yield Observation(count, {"value_band": band})


meter.create_observable_gauge(
    "tracecart.orders.awaiting_payment_result",
    callbacks=[_observe_stuck_orders],
    unit="{order}",
    description=f"Orders in PAYMENT_PROCESSING for more than {STUCK_AFTER_SECONDS}s, by value band.",
)
