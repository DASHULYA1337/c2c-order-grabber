from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.keyboards import cancel_keyboard
from cognito_auth import MfaRequiredException

if TYPE_CHECKING:
    from app import App

logger = logging.getLogger(__name__)

router = Router()


class InviteCodeFSM(StatesGroup):
    waiting_code = State()


class AuthFSM(StatesGroup):
    email     = State()
    password  = State()
    mfa_code  = State()
    trader_id = State()  # User provides trader_id manually


@router.callback_query(F.data == "auth:login")
async def auth_start(callback: CallbackQuery, state: FSMContext, app: App) -> None:
    """Start authentication flow."""
    await state.clear()

    session = app.get_session(callback.message.chat.id)
    if session and session.is_monitoring:
        await callback.answer("Вы уже авторизованы и бот работает.", show_alert=True)
        return

    await callback.message.edit_text(
        "🔐 <b>Авторизация</b>\n\n"
        "Введите ваш email от Cards2Cards:",
        reply_markup=cancel_keyboard("main:menu"),
    )
    await state.set_state(AuthFSM.email)
    await callback.answer()


@router.message(AuthFSM.email)
async def auth_email(message: Message, state: FSMContext) -> None:
    """Handle email input."""
    email = message.text.strip()

    if "@" not in email:
        await message.answer(
            "Пожалуйста, введите корректный email:",
            reply_markup=cancel_keyboard("main:menu"),
        )
        return

    await state.update_data(email=email)
    await message.answer(
        "Введите пароль от Cards2Cards:\n\n"
        "⚠️ Сообщение с паролем будет автоматически удалено для безопасности.",
        reply_markup=cancel_keyboard("main:menu"),
    )
    await state.set_state(AuthFSM.password)


async def _complete_auth_flow(chat_id: int, state: FSMContext, app: App, status_msg: Message) -> None:
    """Complete authentication flow after password input - just ask for trader_id."""
    # We don't authenticate here - just ask for trader_id
    # Authentication will happen in auth_trader_id with MFA support
    await status_msg.edit_text(
        "✅ <b>Credentials сохранены</b>\n\n"
        "Теперь введите ваш <b>Trader ID</b>.\n\n"
        "📍 Где найти Trader ID:\n"
        "1. Зайдите на cards2cards.com\n"
        "2. Скопируйте ваш Trader ID (формат: UUID) из URL\n\n"
        "Пример: <code>97401949-7430-41c1-8d04-d8294b3c4e93</code>",
        reply_markup=cancel_keyboard("main:menu"),
    )
    await state.set_state(AuthFSM.trader_id)


@router.message(AuthFSM.password)
async def auth_password(message: Message, state: FSMContext, app: App) -> None:
    """Handle password input and attempt authentication."""
    password = message.text.strip()
    chat_id = message.chat.id

    # Delete password message immediately
    try:
        await message.delete()
    except Exception as exc:
        logger.warning("Failed to delete password message: %s", exc)

    data = await state.get_data()
    email = data['email']

    # Store password and start auth flow
    await state.update_data(email=email, password=password)

    status_msg = await message.answer("⏳ Авторизация...")
    await _complete_auth_flow(chat_id, state, app, status_msg)


@router.message(AuthFSM.trader_id)
async def auth_trader_id(message: Message, state: FSMContext, app: App) -> None:
    """Handle trader_id input."""
    trader_id = message.text.strip()
    chat_id = message.chat.id

    # Basic validation (UUID format)
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

    if not uuid_pattern.match(trader_id):
        await message.answer(
            "❌ Неверный формат Trader ID.\n\n"
            "Trader ID должен быть в формате UUID:\n"
            "<code>xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx</code>\n\n"
            "Попробуйте еще раз:",
            reply_markup=cancel_keyboard("main:menu"),
        )
        return

    data = await state.get_data()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        await message.answer("❌ Ошибка: сессия авторизации истекла. Начните заново: /start")
        await state.clear()
        return

    # Create user session
    session = app.create_session(
        chat_id   = chat_id,
        username  = email,
        password  = password,
        trader_id = trader_id,
    )

    # Initialize session with MFA callback
    status_msg = await message.answer("⏳ Авторизация...")

    # Load saved refresh_token and device_key from database
    from db.engine import get_session as get_db_session
    from db.repository import AuthorizedUserRepository

    device_key = None
    refresh_token = None
    async with get_db_session() as db_session:
        auth_repo = AuthorizedUserRepository(db_session)
        device_key = await auth_repo.get_device_key(chat_id)
        refresh_token = await auth_repo.get_refresh_token(chat_id)
        if device_key:
            logger.info("Loaded device_key for chat_id=%s", chat_id)
        if refresh_token:
            logger.info("Loaded refresh_token for chat_id=%s", chat_id)

    # Create MFA callback if needed
    mfa_event = asyncio.Event()
    mfa_code_holder = {'code': None}

    async def mfa_callback() -> str:
        """Wait for MFA code from user."""
        await status_msg.edit_text(
            "🔑 Требуется код двухфакторной аутентификации.\n\n"
            "Введите 6-значный код из приложения-аутентификатора:"
        )
        await state.set_state(AuthFSM.mfa_code)
        await mfa_event.wait()
        return mfa_code_holder['code']

    async def on_device_key_changed(new_device_key: str | None) -> None:
        """Save device_key to database when it changes."""
        async with get_db_session() as db_session:
            auth_repo = AuthorizedUserRepository(db_session)
            await auth_repo.save_device_key(chat_id, new_device_key)
            logger.info("Saved device_key for chat_id=%s", chat_id)

    async def on_refresh_token_changed(new_refresh_token: str | None) -> None:
        """Save refresh_token to database when it changes."""
        async with get_db_session() as db_session:
            auth_repo = AuthorizedUserRepository(db_session)
            await auth_repo.save_refresh_token(chat_id, new_refresh_token)
            logger.info("Saved refresh_token for chat_id=%s", chat_id)

    # Store callback data in FSM for MFA handler
    await state.update_data(
        mfa_event=mfa_event,
        mfa_code_holder=mfa_code_holder,
        status_msg_id=status_msg.message_id,
        initializing_session=True,
    )

    try:
        await session.initialize(
            session=app.http_session,
            mfa_callback=mfa_callback,
            device_key=device_key,
            refresh_token=refresh_token,
            on_device_key_changed=on_device_key_changed,
            on_refresh_token_changed=on_refresh_token_changed,
        )

        await status_msg.delete()
        await message.answer(
            "✅ <b>Авторизация успешна!</b>\n\n"
            f"Email: <code>{email}</code>\n"
            f"Trader ID: <code>{trader_id}</code>\n\n"
            "Теперь вы можете запустить мониторинг ордеров через главное меню: /start"
        )
    except Exception as exc:
        logger.exception("Session initialization failed for chat_id=%s", chat_id)
        # Limit error message length and escape HTML
        error_msg = str(exc)[:300]
        error_msg = error_msg.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        await status_msg.edit_text(
            f"❌ <b>Ошибка авторизации</b>\n\n"
            f"<code>{error_msg}</code>\n\n"
            "Попробуйте авторизоваться заново: /start"
        )
        await app.remove_session(chat_id)
        await state.clear()
        return

    await state.clear()


@router.message(AuthFSM.mfa_code)
async def auth_mfa_code(message: Message, state: FSMContext, app: App) -> None:
    """Handle MFA code input."""
    mfa_code = message.text.strip()

    # Delete MFA code message
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    mfa_code_holder = data.get('mfa_code_holder')
    mfa_event = data.get('mfa_event')

    if not mfa_code_holder or not mfa_event:
        await message.answer("❌ Ошибка: сессия авторизации истекла. Начните заново: /start")
        await state.clear()
        return

    # Provide MFA code to waiting callback and trigger event
    # The mfa_callback in _complete_auth_flow is waiting on this event
    mfa_code_holder['code'] = mfa_code
    mfa_event.set()


@router.callback_query(F.data == "auth:logout")
async def auth_logout(callback: CallbackQuery, state: FSMContext, app: App) -> None:
    """Log out and remove session."""
    chat_id = callback.message.chat.id
    session = app.get_session(chat_id)

    if not session:
        await callback.answer("Вы не авторизованы.", show_alert=True)
        return

    await app.remove_session(chat_id)
    await state.clear()

    from bot.keyboards import main_menu_keyboard
    await callback.message.edit_text(
        "🚪 Вы вышли из системы.\n\nДля повторной авторизации нажмите кнопку ниже.",
        reply_markup=main_menu_keyboard(is_running=False, is_authenticated=False),
    )
    await callback.answer("Вы успешно вышли из системы.")


# ============================================================================
# Invite Code Handlers
# ============================================================================

@router.callback_query(F.data == "invite:enter")
async def invite_code_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start invite code entry flow."""
    await state.clear()
    await callback.message.edit_text(
        "🔐 <b>Доступ по приглашению</b>\n\n"
        "Этот бот доступен только по приглашениям.\n"
        "Введите пригласительный код:",
    )
    await state.set_state(InviteCodeFSM.waiting_code)
    await callback.answer()


@router.message(InviteCodeFSM.waiting_code)
async def invite_code_check(message: Message, state: FSMContext, app: App) -> None:
    """Check invite code."""
    import config
    from db.engine import get_session
    from db.repository import AuthorizedUserRepository

    code = message.text.strip()
    chat_id = message.chat.id

    # Delete code message for security
    try:
        await message.delete()
    except Exception:
        pass

    # Check if invite code is configured
    if not config.INVITE_CODE:
        await message.answer("❌ Система приглашений не настроена. Обратитесь к администратору.")
        await state.clear()
        return

    # Check code
    if code == config.INVITE_CODE:
        # Authorize user
        async with get_session() as db_session:
            auth_repo = AuthorizedUserRepository(db_session)
            await auth_repo.authorize(chat_id)

        await state.clear()
        from bot.keyboards import main_menu_keyboard
        await message.answer(
            "✅ <b>Код принят!</b>\n\n"
            "Добро пожаловать! Теперь вы можете использовать бота.\n"
            "Для начала работы необходимо авторизоваться с вашим аккаунтом Cards2Cards.",
            reply_markup=main_menu_keyboard(is_running=False, is_authenticated=False),
        )
    else:
        # Invalid code
        data = await state.get_data()
        attempts = data.get('attempts', 0) + 1

        if attempts >= 3:
            await state.clear()
            await message.answer(
                "❌ <b>Превышено количество попыток</b>\n\n"
                "Слишком много неверных попыток ввода кода.\n"
                "Попробуйте позже: /start"
            )
        else:
            await state.update_data(attempts=attempts)
            await message.answer(
                f"❌ Неверный код. Попытка {attempts}/3.\n\n"
                "Попробуйте еще раз:"
            )
