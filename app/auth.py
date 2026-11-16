import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Token, User, now

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: str | None = None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"{salt}:{digest}"


DUMMY_HASH = hash_password("constant dummy password")


def verify_password(password: str, encoded: str):
    return hmac.compare_digest(hash_password(password, encoded.split(":")[0]), encoded)


def token_digest(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_token(db: Session, user: User):
    raw = secrets.token_urlsafe(32)
    db.add(
        Token(
            digest=token_digest(raw),
            user_id=user.id,
            expires_at=now() + timedelta(hours=get_settings().token_hours),
        )
    )
    db.commit()
    return {"access_token": raw, "token_type": "bearer", "expires_in": get_settings().token_hours * 3600}


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
):
    if credentials and len(credentials.credentials) <= 256:
        token = db.get(Token, token_digest(credentials.credentials))
        if token and token.expires_at.timestamp() > now().timestamp():
            user = db.get(User, token.user_id)
            if user:
                return user
    raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
