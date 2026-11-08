from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    AdminCreateUserRequest,
    AdminCreateUserResponse,
    AdminResetPasswordRequest,
    AdminResetPasswordResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    ChangeUsernameRequest,
    ChangeUsernameResponse,
    CurrentUser,
    LoginRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == data.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码错误",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )
    if not verify_password(data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码错误",
        )

    token = create_access_token(
        data={"sub": user.username, "role": user.role, "user_id": user.id}
    )
    return TokenResponse(access_token=token, token_type="bearer")


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> CurrentUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None or role is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )
    return CurrentUser(username=username, role=role)


def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChangePasswordResponse:
    user = db.query(User).filter(User.username == current_user.username).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )
    if not verify_password(payload.current_password, user.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前密码不正确",
        )
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与当前密码相同",
        )
    user.password = get_password_hash(payload.new_password)
    db.commit()
    return ChangePasswordResponse(message="密码修改成功，请重新登录")


@router.post("/change-username", response_model=ChangeUsernameResponse)
def change_username(
    payload: ChangeUsernameRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChangeUsernameResponse:
    user = db.query(User).filter(User.username == current_user.username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if not verify_password(payload.current_password, user.password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")

    new_username = payload.new_username.strip()
    if new_username == user.username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新用户名不能与当前用户名相同")

    exists = db.query(User).filter(User.username == new_username).first()
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已存在")

    user.username = new_username
    db.commit()
    return ChangeUsernameResponse(message="用户名修改成功，请重新登录", username=new_username)


@router.post("/admin/users", response_model=AdminCreateUserResponse)
def admin_create_user(
    payload: AdminCreateUserRequest,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminCreateUserResponse:
    username = payload.username.strip()
    exists = db.query(User).filter(User.username == username).first()
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已存在")

    row = User(
        username=username,
        password=get_password_hash(payload.password),
        nickname=(payload.nickname or None),
        role=payload.role,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return AdminCreateUserResponse(
        id=row.id,
        username=row.username,
        role=row.role,
        nickname=row.nickname,
    )


@router.post("/admin/reset-password", response_model=AdminResetPasswordResponse)
def admin_reset_user_password(
    payload: AdminResetPasswordRequest,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminResetPasswordResponse:
    username = payload.username.strip()
    row = db.query(User).filter(User.username == username).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    row.password = get_password_hash(payload.new_password)
    db.commit()
    return AdminResetPasswordResponse(message="用户密码已重置", username=row.username)
