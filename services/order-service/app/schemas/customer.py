import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.cpf import normalize_cpf


class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120, examples=["Ana Souza"])
    email: EmailStr = Field(max_length=254, examples=["ana.souza@example.com"])
    cpf: str = Field(
        description="Synthetic CPF, with or without punctuation. Stored as 11 digits.",
        examples=["529.982.247-25"],
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("name must have at least 2 characters")
        return value

    @field_validator("email")
    @classmethod
    def _lowercase_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("cpf")
    @classmethod
    def _validate_cpf(cls, value: str) -> str:
        return normalize_cpf(value)


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    cpf: str
    created_at: datetime
