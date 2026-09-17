"""Signing up, logging in, and checking who is making a request."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.config import MIN_PASSWORD_LENGTH, SESSION_HOURS
from app.db import find_session, find_user_by_email, insert_user, save_session


class AuthError(Exception):
    """Raised when a sign up or login cannot go ahead."""


def hash_password(password, salt):
    """Turn a password into a hash that cannot be turned back."""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def register(email, password):
    """Create a new account, if the email is free and the password is long enough."""
    if not email or "@" not in email:
        raise AuthError("That email address does not look right.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError("Please use a longer password.")
    if find_user_by_email(email):
        raise AuthError("That email is already signed up.")
    salt = secrets.token_hex(8)
    user_id = insert_user(email, hash_password(password, salt), salt)
    return start_session(user_id)


def login(email, password):
    """Check an email and password, and start a session when they match."""
    user = find_user_by_email(email)
    if user is None:
        raise AuthError("We could not find that account.")
    if user["password_hash"] != hash_password(password, user["salt"]):
        raise AuthError("That password is not right.")
    return start_session(user["id"])


def start_session(user_id):
    token = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    save_session(token, user_id, expires.isoformat())
    return token


def user_id_for_token(token):
    """Work out who a request belongs to, or None when the session is gone or old."""
    if not token:
        return None
    session = find_session(token)
    if session is None:
        return None
    if datetime.fromisoformat(session["expires_at"]) < datetime.now(timezone.utc):
        return None
    return session["user_id"]
