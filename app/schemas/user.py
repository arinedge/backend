import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# ─── Request Schemas ────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    full_name: str = Field(min_length=1, max_length=150)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)
    mobile: str | None = Field(default=None, max_length=20)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if v != info.data.get("password"):
            raise ValueError("Passwords do not match")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if v != info.data.get("new_password"):
            raise ValueError("Passwords do not match")
        return v


class EmailVerifyRequest(BaseModel):
    token: str


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    mobile: str | None = Field(default=None, max_length=20)


# ─── Response Schemas ───────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    public_id: str
    username: str
    full_name: str
    email: str
    mobile: str | None
    is_email_verified: bool
    is_logged_in: bool
    last_login_at: datetime | None
    login_count: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email_verified: bool
    user: UserOut


class MessageResponse(BaseModel):
    message: str


class UserResponse(BaseModel):
    user: UserOut


class UserInDB(UserOut):
    hashed_password: str
    email_verify_token: str | None
    email_verify_token_expires: datetime | None
    password_reset_token: str | None
    password_reset_token_expires: datetime | None
