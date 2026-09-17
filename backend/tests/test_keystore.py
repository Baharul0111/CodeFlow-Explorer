from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.errors import InvalidKeyError
from app.llm.keystore import KeyStore
from app.models.db import Database
from app.models.orm import ApiKeyRecord

KEY = "sk-ant-api03-thisisatestkey-0123456789"


@pytest.fixture
async def db_session(settings: Settings):  # type: ignore[no-untyped-def]
    db = Database(settings.database_url)
    await db.create_all()
    async with db.session_factory() as session:
        yield session
    await db.dispose()


def test_token_is_opaque_and_key_stays_server_side() -> None:
    store = KeyStore("secret")
    token = store.put(KEY)
    assert KEY not in token
    assert store.get(token) == KEY
    assert store.fingerprint_of(token) == KEY[-4:]


def test_unknown_token_requires_reconnect() -> None:
    store = KeyStore("secret")
    assert store.get("nope") is None
    with pytest.raises(InvalidKeyError):
        store.require("nope")


def test_forget_removes_key() -> None:
    store = KeyStore("secret")
    token = store.put(KEY)
    store.forget(token)
    assert store.get(token) is None


def test_expired_sessions_are_dropped() -> None:
    store = KeyStore("secret", ttl_seconds=0)
    token = store.put(KEY)
    assert store.get(token) is None


async def test_remember_encrypts_at_rest_and_restores(db_session: AsyncSession) -> None:
    store = KeyStore("secret")
    token = store.put(KEY)
    await store.remember(db_session, token, KEY)

    row = (await db_session.execute(select(ApiKeyRecord))).scalar_one()
    assert KEY not in row.ciphertext  # stored encrypted, never in plain text
    assert token not in row.session_token_hash  # the token itself is hashed

    fresh = KeyStore("secret")
    assert await fresh.restore(db_session, token) == KEY

    wrong_secret = KeyStore("different-secret")
    assert await wrong_secret.restore(db_session, token) is None


async def test_forget_everywhere_deletes_the_row(db_session: AsyncSession) -> None:
    store = KeyStore("secret")
    token = store.put(KEY)
    await store.remember(db_session, token, KEY)
    await store.forget_everywhere(db_session, token)
    count = (
        await db_session.execute(select(func.count(ApiKeyRecord.session_token_hash)))
    ).scalar_one()
    assert count == 0
    assert store.get(token) is None
