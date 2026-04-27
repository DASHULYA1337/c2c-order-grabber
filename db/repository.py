from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuthorizedUser, OrderLog, Settings, Subscriber


class SettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> Optional[Settings]:
        result = await self._session.execute(select(Settings).where(Settings.id == 1))
        return result.scalar_one_or_none()

    async def get_or_create(self) -> Settings:
        settings = await self.get()
        if settings is None:
            settings = Settings(id=1)
            self._session.add(settings)
            await self._session.commit()
            await self._session.refresh(settings)
        return settings

    async def update(self, **kwargs) -> Settings:
        settings = await self.get_or_create()
        for key, value in kwargs.items():
            setattr(settings, key, value)
        await self._session.commit()
        await self._session.refresh(settings)
        return settings


class SubscriberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, chat_id: int) -> None:
        existing = await self._session.get(Subscriber, chat_id)
        if existing is None:
            self._session.add(Subscriber(chat_id=chat_id))
            await self._session.commit()

    async def get_all(self) -> List[int]:
        result = await self._session.execute(select(Subscriber.chat_id))
        return list(result.scalars().all())


class OrderLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, chat_id: int, order_slug: str, amount: Optional[float], status: str) -> OrderLog:
        entry = OrderLog(
            chat_id=chat_id,
            order_slug=order_slug,
            amount=amount,
            status=status,
            taken_at=datetime.utcnow(),
        )
        self._session.add(entry)
        await self._session.commit()
        return entry

    async def count_taken(self, chat_id: int) -> int:
        result = await self._session.execute(
            select(func.count()).where(
                (OrderLog.status == "taken") & (OrderLog.chat_id == chat_id)
            )
        )
        return result.scalar_one()

    async def count_failed(self, chat_id: int) -> int:
        result = await self._session.execute(
            select(func.count()).where(
                (OrderLog.status == "failed") & (OrderLog.chat_id == chat_id)
            )
        )
        return result.scalar_one()

    async def last_entries(self, chat_id: int, limit: int = 5) -> List[OrderLog]:
        result = await self._session.execute(
            select(OrderLog)
            .where(OrderLog.chat_id == chat_id)
            .order_by(OrderLog.taken_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class AuthorizedUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_authorized(self, chat_id: int) -> bool:
        """Check if user is authorized (entered valid invite code)."""
        result = await self._session.get(AuthorizedUser, chat_id)
        return result is not None

    async def authorize(self, chat_id: int) -> None:
        """Mark user as authorized."""
        existing = await self._session.get(AuthorizedUser, chat_id)
        if existing is None:
            self._session.add(AuthorizedUser(chat_id=chat_id))
            await self._session.commit()

    async def get_refresh_token(self, chat_id: int) -> Optional[str]:
        """Get stored refresh token for user."""
        user = await self._session.get(AuthorizedUser, chat_id)
        return user.refresh_token if user else None

    async def save_refresh_token(self, chat_id: int, refresh_token: Optional[str]) -> None:
        """Save refresh token for user."""
        user = await self._session.get(AuthorizedUser, chat_id)
        if user:
            user.refresh_token = refresh_token
            await self._session.commit()

    async def get_device_key(self, chat_id: int) -> Optional[str]:
        """Get stored device key for user."""
        user = await self._session.get(AuthorizedUser, chat_id)
        return user.device_key if user else None

    async def save_device_key(self, chat_id: int, device_key: Optional[str]) -> None:
        """Save device key for user."""
        user = await self._session.get(AuthorizedUser, chat_id)
        if user:
            user.device_key = device_key
            await self._session.commit()
