from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

MAX_EMAIL_LENGTH = 255


def _normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > MAX_EMAIL_LENGTH:
        raise ValueError("Email is too long.")
    return email


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name")
    @classmethod
    def clean_full_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Full name cannot be empty.")
        return value

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return _normalize_email(value)


class UserLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return _normalize_email(value)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: EmailStr
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"