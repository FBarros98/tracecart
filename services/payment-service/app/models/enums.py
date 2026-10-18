from enum import StrEnum


class PaymentMethod(StrEnum):
    PIX = "PIX"
    CREDIT_CARD = "CREDIT_CARD"
    BOLETO = "BOLETO"


class PaymentStatus(StrEnum):
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ERROR = "ERROR"


FINAL_PAYMENT_STATUSES = frozenset({PaymentStatus.APPROVED, PaymentStatus.DECLINED})
