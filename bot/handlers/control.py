from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards import main_menu_keyboard
from db.engine import get_session
from db.repository import OrderLogRepository

router = Router()


@router.callback_query(F.data == "bot:start")
async def bot_start(callback: CallbackQuery, app) -> None:
    chat_id = callback.message.chat.id
    session = app.get_session(chat_id)

    if not session:
        await callback.answer("Сначала авторизуйтесь!", show_alert=True)
        return

    if session.is_monitoring:
        await callback.answer("Бот уже запущен.", show_alert=True)
        return

    # Check if session is initialized
    if not session.api_client:
        await callback.answer("Ошибка: сессия не инициализирована. Попробуйте авторизоваться заново: /start", show_alert=True)
        return

    await callback.message.edit_text("Запускаю бота, подождите...")

    # Start monitoring with callbacks
    async def on_taken(slug: str, amount: float | None) -> None:
        await app._on_taken(chat_id, slug, amount)

    async def on_failed(slug: str, amount: float | None) -> None:
        await app._on_failed(chat_id, slug, amount)

    async def on_startup_ok(min_amt: float | None, max_amt: float | None) -> None:
        await app._on_startup_ok(chat_id, min_amt, max_amt)

    async def on_error(exc: Exception) -> None:
        await app._on_monitor_error(chat_id, exc)

    await session.start_monitoring(
        on_taken      = on_taken,
        on_failed     = on_failed,
        on_startup_ok = on_startup_ok,
        on_error      = on_error,
    )

    await callback.message.edit_text(
        "✅ Бот запущен. Начинаю мониторинг новых ордеров.",
        reply_markup=main_menu_keyboard(True, is_authenticated=True),
    )
    await callback.answer()


@router.callback_query(F.data == "bot:stop")
async def bot_stop(callback: CallbackQuery, app) -> None:
    chat_id = callback.message.chat.id
    session = app.get_session(chat_id)

    if not session:
        await callback.answer("Вы не авторизованы.", show_alert=True)
        return

    if not session.is_monitoring:
        await callback.answer("Бот уже остановлен.", show_alert=True)
        return

    await callback.message.edit_text("Останавливаю бота...")
    await session.stop_monitoring()
    await callback.message.edit_text(
        "⛔ Бот остановлен.",
        reply_markup=main_menu_keyboard(False, is_authenticated=True),
    )
    await callback.answer()


@router.callback_query(F.data == "stats:show")
async def stats_show(callback: CallbackQuery, app) -> None:
    chat_id = callback.message.chat.id
    session = app.get_session(chat_id)

    if not session:
        await callback.answer("Вы не авторизованы.", show_alert=True)
        return

    async with get_session() as db_session:
        log_repo = OrderLogRepository(db_session)
        taken  = await log_repo.count_taken()
        failed = await log_repo.count_failed()
        last   = await log_repo.last_entries(5)

    lines = [
        "<b>Статистика</b>\n",
        f"Текущая сессия:",
        f"  Взято: {session.orders_taken}",
        f"  Ошибок: {session.orders_failed}",
        "",
        f"Всего в БД:",
        f"  Взято: {taken}",
        f"  Ошибок: {failed}",
    ]

    if last:
        lines.append("\nПоследние 5 записей:")
        for entry in last:
            amount_str = f"{entry.amount:,.0f} RUB" if entry.amount else "—"
            dt_str = entry.taken_at.strftime("%d.%m %H:%M")
            icon = "✅" if entry.status == "taken" else "❌"
            lines.append(
                f"{icon} {dt_str}  {amount_str}  <code>{entry.order_slug[:20]}…</code>"
            )

    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data.startswith("retry:"))
async def retry_order(callback: CallbackQuery, app) -> None:
    chat_id = callback.message.chat.id
    session = app.get_session(chat_id)

    if not session:
        await callback.answer("Вы не авторизованы.", show_alert=True)
        return

    if not session.is_monitoring:
        await callback.answer("Бот не запущен, повтор невозможен.", show_alert=True)
        return

    slug = callback.data.split(":", 1)[1]
    session.retry_order(slug)

    await callback.message.edit_text(
        f"🔄 Повтор попытки для ордера <code>{slug}</code> запланирован.",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("skip:"))
async def skip_order(callback: CallbackQuery) -> None:
    slug = callback.data.split(":", 1)[1]
    await callback.message.edit_text(
        f"⏭ Ордер <code>{slug}</code> пропущен.",
    )
    await callback.answer()
