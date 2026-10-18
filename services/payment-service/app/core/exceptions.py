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


class SimulatedDatabaseError(AppError):
    """Injected intermittent database failure (DATABASE_FAILURE_*)."""

    status_code = 503


class SimulatedUnexpectedError(RuntimeError):
    """Injected internal error (UNEXPECTED_ERROR_*). Deliberately not an AppError: it becomes a 500."""
