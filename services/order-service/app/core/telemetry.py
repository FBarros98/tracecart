"""Manual OpenTelemetry helpers (spans only; the SDK is configured by `opentelemetry-instrument`)."""

from decimal import Decimal

from opentelemetry import trace

tracer = trace.get_tracer("tracecart.order-service")

MID_VALUE_THRESHOLD = Decimal("300.00")
HIGH_VALUE_THRESHOLD = Decimal("1000.00")


def value_band(amount: Decimal) -> str:
    """Bucket an order total into a low-cardinality band for span attributes."""
    if amount >= HIGH_VALUE_THRESHOLD:
        return "high"
    if amount >= MID_VALUE_THRESHOLD:
        return "mid"
    return "low"
