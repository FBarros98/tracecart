class AppError(Exception):
    """Base class for errors that map to a safe HTTP response."""

    status_code: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class BusinessRuleError(AppError):
    status_code = 422


class PaymentServiceError(AppError):
    """The Payment Service could not give a definitive answer: the outcome is unknown."""

    status_code = 502


class PaymentServiceTimeoutError(PaymentServiceError):
    status_code = 504


class PaymentServiceUnavailableError(PaymentServiceError):
    status_code = 502
