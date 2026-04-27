import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL
from db.models import Base

os.makedirs("data", exist_ok=True)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

_MIGRATIONS = [
    "ALTER TABLE settings ADD COLUMN poll_interval REAL NOT NULL DEFAULT 1.0",
    "ALTER TABLE authorized_users ADD COLUMN refresh_token TEXT",
    "ALTER TABLE authorized_users ADD COLUMN device_key TEXT",
    "ALTER TABLE order_log ADD COLUMN chat_id INTEGER NOT NULL DEFAULT 0",
]


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for sql in _MIGRATIONS:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
