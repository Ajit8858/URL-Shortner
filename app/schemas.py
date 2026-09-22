from datetime import datetime

from pydantic import BaseModel, EmailStr, HttpUrl, field_validator


class ShortenRequest(BaseModel):
    long_url: HttpUrl
    custom_alias: str | None = None
    expires_in_days: int | None = None

    @field_validator("custom_alias")
    @classmethod
    def alias_must_be_url_safe(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.isalnum():
            raise ValueError("custom_alias must be alphanumeric")
        return v


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str
    created_at: datetime
    expires_at: datetime | None = None


class URLStats(BaseModel):
    short_code: str
    long_url: str
    click_count: int
    created_at: datetime
    is_active: bool


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    api_key: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
