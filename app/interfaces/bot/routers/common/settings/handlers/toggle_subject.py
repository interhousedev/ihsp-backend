"""Toggle one subject of the mark notification filter (BOT-13)."""

from app.interfaces.bot.routers.common.settings.render import render_subjects
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.settings_patch import subject_patch
from app.interfaces.bot.utilities.reply_edit import answer_callback, show
from app.shared.contracts.callbacks import SettingsCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery


async def toggle_subject(
    callback: CallbackQuery,
    callback_data: SettingsCb,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Flip the subject at the pressed position and re-render the list."""
    prefs = await services.directory.get_preferences(user.id)
    summary = await services.marks.subjects_summary(user.id, None)
    ordered = sorted(
        summary, key=lambda item: (item.name.lower(), str(item.subject_id))
    )
    index = int(callback_data.value) if callback_data.value.isdigit() else -1
    patch = subject_patch(prefs, [item.subject_id for item in ordered], index)
    if patch is None:
        await answer_callback(callback)
        return
    await services.identity_commands.update_preferences(user.id, patch)
    await show(callback, await render_subjects(user, services, i18n))
