from decimal import Decimal

from opentelemetry import trace

tracer = trace.get_tracer("tracecart.payment-service")

MEDIUM_RISK_THRESHOLD = Decimal("300.00")
HIGH_RISK_THRESHOLD = Decimal("1000.00")


def risk_level(amount: Decimal) -> str:
    if amount >= HIGH_RISK_THRESHOLD:
        return "high"
    if amount >= MEDIUM_RISK_THRESHOLD:
        return "medium"
    return "low"
