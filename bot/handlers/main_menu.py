from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from bot.keyboards import main_menu_keyboard
from db.engine import get_session
from db.repository import SettingsRepository

from aiogram import F

router = Router()


@router.callback_query(F.data == "main:menu")
async def main_menu(callback: CallbackQuery, app) -> None:
    """Show main menu."""
    chat_id = callback.message.chat.id
    user_session = app.get_session(chat_id)

    if not user_session:
        await callback.message.edit_text(
            "<b>Cards2Cards бот</b>\n\n"
            "Вы не авторизованы. Для начала работы нажмите кнопку ниже.",
            reply_markup=main_menu_keyboard(is_running=False, is_authenticated=False),
        )
        await callback.answer()
        return

    filter_parts = []
    if user_session.min_amount is not None:
        filter_parts.append(f"от {user_session.min_amount:,.0f}")
    if user_session.max_amount is not None:
        filter_parts.append(f"до {user_session.max_amount:,.0f}")
    filter_line = (
        f"Фильтр суммы: {' '.join(filter_parts)} ₽"
        if filter_parts
        else "Фильтр суммы: не задан"
    )

    status_line = "Статус: ✅ работает" if user_session.is_monitoring else "Статус: ⛔ остановлен"

    await callback.message.edit_text(
        f"<b>Cards2Cards бот</b>\n\n"
        f"Аккаунт: <code>{user_session.username}</code>\n"
        f"{status_line}\n"
        f"{filter_line}\n\n"
        f"Взято ордеров: {user_session.orders_taken}\n"
        f"Ошибок: {user_session.orders_failed}",
        reply_markup=main_menu_keyboard(user_session.is_monitoring, is_authenticated=True),
    )
    await callback.answer()


@router.message(CommandStart())
async def cmd_start(message: Message, app) -> None:
    import config
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from db.engine import get_session
    from db.repository import AuthorizedUserRepository

    chat_id = message.chat.id

    # Check if invite code system is enabled
    if config.INVITE_CODE:
        async with get_session() as db_session:
            auth_repo = AuthorizedUserRepository(db_session)
            is_authorized = await auth_repo.is_authorized(chat_id)

        if not is_authorized:
            # User needs to enter invite code first
            builder = InlineKeyboardBuilder()
            builder.button(text="🔑 Ввести код приглашения", callback_data="invite:enter")

            await message.answer(
                "<b>Cards2Cards бот</b>\n\n"
                "Этот бот доступен только по приглашениям.\n\n"
                "Для использования бота необходим пригласительный код.",
                reply_markup=builder.as_markup(),
            )
            return

    user_session = app.get_session(chat_id)

    if not user_session:
        # User not authenticated
        await message.answer(
            "<b>Cards2Cards бот</b>\n\n"
            "Добро пожаловать! Этот бот позволяет автоматически мониторить и захватывать новые ордера на Cards2Cards.\n\n"
            "Для начала работы необходимо авторизоваться с вашим аккаунтом Cards2Cards.\n\n"
            "⚠️ <b>Безопасность:</b>\n"
            "• Ваши credentials хранятся только в памяти\n"
            "• При рестарте бота нужно авторизоваться заново\n"
            "• Пароли автоматически удаляются из чата",
            reply_markup=main_menu_keyboard(is_running=False, is_authenticated=False),
        )
        return

    # User authenticated
    filter_parts = []
    if user_session.min_amount is not None:
        filter_parts.append(f"от {user_session.min_amount:,.0f}")
    if user_session.max_amount is not None:
        filter_parts.append(f"до {user_session.max_amount:,.0f}")
    filter_line = (
        f"Фильтр суммы: {' '.join(filter_parts)} ₽"
        if filter_parts
        else "Фильтр суммы: не задан"
    )

    status_line = "Статус: ✅ работает" if user_session.is_monitoring else "Статус: ⛔ остановлен"

    await message.answer(
        f"<b>Cards2Cards бот</b>\n\n"
        f"Аккаунт: <code>{user_session.username}</code>\n"
        f"{status_line}\n"
        f"{filter_line}\n\n"
        f"Взято ордеров: {user_session.orders_taken}\n"
        f"Ошибок: {user_session.orders_failed}",
        reply_markup=main_menu_keyboard(user_session.is_monitoring, is_authenticated=True),
    )
