from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Rate = Annotated[float, Field(ge=0.0, le=1.0)]


class Settings(BaseSettings):
    """Configuration loaded exclusively from environment variables."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    service_name: str = "tracecart-payment-service"
    environment: str = "local"
    log_level: LogLevel = "INFO"

    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "tracecart_payments"
    db_user: str
    db_password: SecretStr
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=5, ge=0)
    db_connect_timeout_seconds: int = Field(default=5, ge=1)

    # Fault injection: every fault is disabled by default and independent of the others.
    payment_decline_enabled: bool = False
    payment_decline_rate: Rate = 0.0
    payment_latency_enabled: bool = False
    payment_latency_min_ms: int = Field(default=0, ge=0)
    payment_latency_max_ms: int = Field(default=0, ge=0)
    database_failure_enabled: bool = False
    database_failure_rate: Rate = 0.0
    unexpected_error_enabled: bool = False
    unexpected_error_rate: Rate = 0.0

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _validate_latency_range(self) -> Self:
        if self.payment_latency_max_ms < self.payment_latency_min_ms:
            raise ValueError("PAYMENT_LATENCY_MAX_MS must be >= PAYMENT_LATENCY_MIN_MS")
        return self

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
