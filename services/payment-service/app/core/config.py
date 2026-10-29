from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):

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

    # Failure scenario: slow fraud check for high-risk payments (off by default). The delay should be
    # longer than the Order Service's PAYMENT_SERVICE_TIMEOUT_SECONDS so those orders end up unknown.
    fraud_check_delay_enabled: bool = False
    fraud_check_delay_seconds: float = Field(default=8.0, gt=0)

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

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
