from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    nickname: str | None = None
    role: str
    is_active: bool


class CurrentUser(BaseModel):
    username: str
    role: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)


class ChangePasswordResponse(BaseModel):
    message: str


class ChangeUsernameRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_username: str = Field(..., min_length=3, max_length=50)


class ChangeUsernameResponse(BaseModel):
    message: str
    username: str


class AdminCreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(default="user", pattern=r"^(admin|user|auditor)$")
    nickname: str | None = Field(default=None, max_length=50)


class AdminCreateUserResponse(BaseModel):
    id: int
    username: str
    role: str
    nickname: str | None = None


class AdminResetPasswordRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    new_password: str = Field(..., min_length=6, max_length=128)


class AdminResetPasswordResponse(BaseModel):
    message: str
    username: str
