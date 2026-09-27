from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class AuthInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        email = value.casefold()
        if len(email) > 254:
            raise ValueError("Email must be at most 254 characters")
        return email

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        if not password.strip():
            raise ValueError("Password must not be blank")
        if "\x00" in password or len(password.encode("utf-8")) > 72:
            raise ValueError(
                "Password must be at most 72 UTF-8 bytes and contain no null characters"
            )
        return value


class RegisterInput(AuthInput):
    organization_name: str = Field(min_length=1, max_length=120)
    full_name: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=8, max_length=72)

    @field_validator("organization_name", "full_name", mode="before")
    @classmethod
    def trim_names(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class UserSummary(BaseModel):
    id: str
    full_name: str
    email: str


class OrganizationSummary(BaseModel):
    id: str
    name: str


class SessionSummary(BaseModel):
    user: UserSummary
    organization: OrganizationSummary
    expires_at: datetime
