from enum import StrEnum


class ProductCategory(StrEnum):
    ELECTRONICS = "ELECTRONICS"
    BOOKS = "BOOKS"
    CLOTHING = "CLOTHING"
    HOME = "HOME"
    FOOD = "FOOD"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    PAYMENT_PROCESSING = "PAYMENT_PROCESSING"
    PAID = "PAID"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    CANCELLED = "CANCELLED"


class PaymentMethod(StrEnum):
    PIX = "PIX"
    CREDIT_CARD = "CREDIT_CARD"
    BOLETO = "BOLETO"
