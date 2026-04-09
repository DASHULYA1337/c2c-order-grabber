from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_keyboard(is_running: bool, is_authenticated: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if not is_authenticated:
        builder.button(text="🔐 Авторизоваться", callback_data="auth:login")
    elif is_running:
        builder.button(text="⏹ Остановить бота", callback_data="bot:stop")
    else:
        builder.button(text="▶️ Запустить бота", callback_data="bot:start")

    if is_authenticated:
        builder.button(text="⚙️ Настройки",  callback_data="settings:menu")
        builder.button(text="📊 Статистика",  callback_data="stats:show")
        builder.button(text="🚪 Выйти",       callback_data="auth:logout")

    builder.adjust(1)
    return builder.as_markup()


def settings_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Фильтры суммы",   callback_data="settings:filters")
    builder.button(text="⏱ Интервал опроса", callback_data="settings:poll_interval")
    builder.button(text="◀️ Назад",           callback_data="settings:back")
    builder.adjust(1)
    return builder.as_markup()


def cancel_keyboard(back_to: str = "settings:menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if back_to == "main:menu":
        builder.button(text="◀️ Назад", callback_data=back_to)
    else:
        builder.button(text="✖️ Отмена", callback_data=back_to)
    return builder.as_markup()


def filters_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Сохранить", callback_data="filters:save")
    builder.button(text="✏️ Изменить",  callback_data="filters:edit")
    builder.button(text="✖️ Отмена",    callback_data="settings:menu")
    builder.adjust(2, 1)
    return builder.as_markup()
