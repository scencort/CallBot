import asyncio
import html
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from telegram import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


SCRIPT_STEPS = [
    {"title": "Приветствие", "prompt": "Алло, здравствуйте, по квартире звоню.", "expects_note": False},
    {"title": "Вопросы", "prompt": "Когда показы проводите?", "expects_note": True, "field": "Когда показы проводите?"},
    {"title": "Вопросы", "prompt": "Вы собственник? Или агент / риэлтор?", "expects_note": True, "field": "Вы собственник? Или агент / риэлтор?"},
    {"title": "Вопросы", "prompt": "Что по документам основания у Вас?", "expects_note": True, "field": "Что по документам основания у Вас?"},
    {"title": "Вопросы", "prompt": "Кредит под залог недвижимости не брали?", "expects_note": True, "field": "Кредит под залог недвижимости не брали?"},
    {"title": "Вопросы", "prompt": "Как давно владеете квартирой?", "expects_note": True, "field": "Как давно владеете квартирой?"},
    {"title": "Вопросы", "prompt": "Как давно делали ремонт?", "expects_note": True, "field": "Как давно делали ремонт?"},
    {"title": "Вопросы", "prompt": "Что меняли в квартире?", "expects_note": True, "field": "Что меняли в квартире?"},
    {"title": "Вопросы", "prompt": "Что остаётся в квартире после продажи?", "expects_note": True, "field": "Что остаётся в квартире после продажи?"},
    {"title": "Вопросы", "prompt": "Парковка во дворе закрытая?", "expects_note": True, "field": "Парковка во дворе закрытая?"},
    {"title": "Вопросы", "prompt": "Куда окна выходят?", "expects_note": True, "field": "Куда окна выходят?"},
    {"title": "Вопросы", "prompt": "Почему продаёте?", "expects_note": True, "field": "Почему продаёте?"},
    {
        "title": "Вопросы",
        "prompt": "Сколько собственников? Есть ли несовершеннолетние или недееспособные?",
        "expects_note": True,
        "field": "Сколько собственников? Есть ли несовершеннолетние или недееспособные?",
    },
    {
        "title": "Вопросы",
        "prompt": "Какой торг возможен в случае быстрой сделки с наличными?",
        "expects_note": True,
        "field": "Какой торг возможен в случае быстрой сделки с наличными?",
    },
    {
        "title": "Познакомиться",
        "prompt": "Меня зовут ... Я специалист службы качества компании Этажи. Как к Вам можно обращаться?",
        "expects_note": True,
        "field": "Как к Вам можно обращаться?",
    },
    {
        "title": "Предложение",
        "prompt": (
            "Предлагаю Вам бесплатное размещение на сайте Этажи. Это поможет получить больше "
            "покупателей и продать объект максимально выгодно. Хотите, я размещу Ваш объект "
            "на нашем сайте бесплатно?"
        ),
        "expects_note": True,
        "field": "Реакция на предложение бесплатного размещения",
    },
    {
        "title": "Условие",
        "prompt": (
            "Также мы можем провести анализ объекта: оценка рыночной стоимости, осмотр, "
            "первичная проверка документов, план выгодной продажи, схема сделки и контент-план. "
            "Что ответил клиент?"
        ),
        "expects_note": True,
        "field": "Реакция на анализ объекта",
    },
]

TOTAL_STEPS = len(SCRIPT_STEPS)


@dataclass
class CallSession:
    step_index: int = 0
    notes: list[tuple[str, str]] = field(default_factory=list)
    waiting_for_decline_reason: bool = False
    finished: bool = False
    agreed: bool | None = None
    decline_reason: str | None = None
    call_id: int | None = None
    started_at: str | None = None


def build_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🚀 Начать звонок"), KeyboardButton("🔄 Новый звонок")],
            [KeyboardButton("📝 Сводка"), KeyboardButton("📚 Сегодня")],
            [KeyboardButton("🛑 Сбросить")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Пиши заметку по клиенту одним сообщением...",
    )


def build_greeting_keyboard(prompt: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📋 Скопировать приветствие", copy_text=CopyTextButton(prompt[:256]))],
            [InlineKeyboardButton("➡️ Дальше", callback_data="next_step")],
        ]
    )


def build_step_keyboard(prompt: str, step_index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📋 Скопировать вопрос", copy_text=CopyTextButton(prompt[:256]))],
            [
                InlineKeyboardButton("⏭ Пропустить заметку", callback_data=f"skip:{step_index}"),
                InlineKeyboardButton("🛑 Завершить звонок", callback_data="finish_early"),
            ],
        ]
    )


def build_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Согласен", callback_data="agree"),
                InlineKeyboardButton("❌ Не согласен", callback_data="decline"),
            ]
        ]
    )


def build_today_calls_keyboard(calls: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for payload in reversed(calls[-20:]):
        call_id = int(payload.get("call_id", 0))
        finished_at = str(payload.get("finished_at", ""))
        time_part = finished_at[11:16] if len(finished_at) >= 16 else "--:--"
        status = short_status(payload.get("agreed"))
        label = f"#{call_id} {status} {time_part}"
        rows.append([InlineKeyboardButton(label[:64], callback_data=f"open_call:{call_id}")])
    return InlineKeyboardMarkup(rows)


def get_session(context: ContextTypes.DEFAULT_TYPE) -> CallSession:
    session = context.user_data.get("session")
    if session is None:
        session = CallSession()
        context.user_data["session"] = session
    return session


def history_file() -> Path:
    return Path(__file__).with_name("calls_history.jsonl")


def now_label() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_label() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def escape(value: Any) -> str:
    return html.escape(str(value), quote=False)


def short_status(agreed: bool | None) -> str:
    if agreed is True:
        return "✅ Согласен"
    if agreed is False:
        return "❌ Отказ"
    return "⏳ В процессе"


def next_call_id() -> int:
    path = history_file()
    if not path.exists():
        return 1

    last_id = 0
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            last_id = max(last_id, int(payload.get("call_id", 0)))
    return last_id + 1


def serialize_session(session: CallSession) -> dict[str, Any]:
    return {
        "call_id": session.call_id,
        "started_at": session.started_at,
        "finished_at": now_label(),
        "agreed": session.agreed,
        "decline_reason": session.decline_reason,
        "notes": [{"question": question, "answer": answer} for question, answer in session.notes],
    }


def save_completed_call(session: CallSession) -> None:
    if session.call_id is None:
        session.call_id = next_call_id()
    if session.started_at is None:
        session.started_at = now_label()

    with history_file().open("a", encoding="utf-8") as file:
        file.write(json.dumps(serialize_session(session), ensure_ascii=False) + "\n")


def load_today_calls() -> list[dict[str, Any]]:
    path = history_file()
    if not path.exists():
        return []

    items: list[dict[str, Any]] = []
    current_day = today_label()
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(payload.get("finished_at", "")).startswith(current_day):
                items.append(payload)
    return items


def format_rich_intro() -> str:
    return (
        "<h3>📞 Сценарий звонка запущен</h3>"
        "<p>Я веду тебя по скрипту звонка и собираю заметки по клиенту.</p>"
        "<details>"
        "<summary>Как пользоваться</summary>"
        "<ul>"
        "<li>Говоришь клиенту фразу из шага.</li>"
        "<li>Пишешь заметку одним сообщением.</li>"
        "<li>Если заметка не нужна, жмёшь «Пропустить».</li>"
        "<li>В конце фиксируешь согласие или отказ.</li>"
        "</ul>"
        "</details>"
    )


def format_step_rich(step_index: int) -> str:
    step = SCRIPT_STEPS[step_index]
    action_html = (
        "<p><b>Действие:</b> проговори фразу и отправь заметку одним сообщением.</p>"
        if step["expects_note"]
        else "<p><b>Действие:</b> просто поздоровайся и нажми «Дальше».</p>"
    )
    return (
        f"<h4>{escape(step['title'])}</h4>"
        f"<p><b>Шаг:</b> {step_index + 1} / {TOTAL_STEPS}</p>"
        f"<blockquote>{escape(step['prompt'])}</blockquote>"
        f"{action_html}"
        "<details>"
        "<summary>Подсказка</summary>"
        "<p>Пиши коротко: имя, собственник или агент, торг, документы, причина продажи.</p>"
        "</details>"
    )


def preview_text(payload: dict[str, Any]) -> str:
    notes = payload.get("notes", [])
    if not notes:
        return "Без заметок"
    first = str(notes[0].get("answer", "")).strip()
    if not first:
        return "Без заметок"
    return first[:44] + ("…" if len(first) > 44 else "")


def format_today_summary_rich() -> str:
    calls = load_today_calls()
    if not calls:
        return "<h3>📚 Звонки за сегодня</h3><p>Пока ни одного завершённого звонка нет.</p>"

    rows: list[str] = []
    for payload in calls[-20:]:
        rows.append(
            "<tr>"
            f"<td><b>#{escape(payload.get('call_id', ''))}</b></td>"
            f"<td>{escape(short_status(payload.get('agreed')))}</td>"
            f"<td>{escape(str(payload.get('finished_at', ''))[11:16])}</td>"
            f"<td>{escape(preview_text(payload))}</td>"
            "</tr>"
        )

    return (
        f"<h3>📚 Звонки за {escape(today_label())}</h3>"
        f"<p><b>Всего:</b> {len(calls)}</p>"
        "<table>"
        "<tr><th>ID</th><th>Статус</th><th>Время</th><th>Коротко</th></tr>"
        f"{''.join(rows)}"
        "</table>"
        "<p>Нажми кнопку нужного звонка ниже, чтобы открыть все ответы клиента.</p>"
    )


def format_saved_call_rich(payload: dict[str, Any]) -> str:
    notes = payload.get("notes", [])
    notes_html = ""
    for item in notes:
        notes_html += (
            f"<h4>{escape(item.get('question', ''))}</h4>"
            f"<blockquote>{escape(item.get('answer', ''))}</blockquote>"
        )

    decline_html = ""
    if payload.get("agreed") is False and payload.get("decline_reason"):
        decline_html = (
            "<h4>Причина отказа</h4>"
            f"<blockquote>{escape(payload.get('decline_reason'))}</blockquote>"
        )

    return (
        f"<h3>📋 Звонок #{escape(payload.get('call_id', ''))}</h3>"
        "<table>"
        "<tr><th>Статус</th><th>Время</th></tr>"
        f"<tr><td>{escape(short_status(payload.get('agreed')))}</td>"
        f"<td>{escape(payload.get('finished_at', ''))}</td></tr>"
        "</table>"
        f"{notes_html or '<p>Заметок нет.</p>'}"
        f"{decline_html}"
    )


def format_current_summary_rich(session: CallSession, completed: bool = False) -> str:
    answered = sum(1 for _, answer in session.notes if answer != "Пропущено")
    skipped = sum(1 for _, answer in session.notes if answer == "Пропущено")

    if session.notes:
        recent = "<details open><summary>Последние заметки</summary>"
        for question, answer in session.notes[-3:]:
            recent += f"<p><b>{escape(question)}</b></p><blockquote>{escape(answer)}</blockquote>"
        recent += "</details>"
    else:
        recent = "<p>Заметок пока нет.</p>"

    footer = ""
    if completed:
        footer = (
            "<p><b>Полный звонок сохранён в журнал.</b></p>"
            "<p>Открой «📚 Сегодня» и выбери звонок из списка кнопкой.</p>"
        )

    return (
        f"<h3>📋 Звонок #{escape(session.call_id or '—')}</h3>"
        "<table>"
        "<tr><th>Прогресс</th><th>Ответов</th><th>Пропусков</th><th>Статус</th></tr>"
        f"<tr><td>{min(session.step_index, TOTAL_STEPS)} / {TOTAL_STEPS}</td>"
        f"<td>{answered}</td>"
        f"<td>{skipped}</td>"
        f"<td>{escape(short_status(session.agreed))}</td></tr>"
        "</table>"
        f"{recent}"
        f"{footer}"
    )


def find_call_payload(call_id: int) -> dict[str, Any] | None:
    path = history_file()
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if int(payload.get("call_id", 0)) == call_id:
                return payload
    return None


def flatten_rich_text(rich_html: str) -> str:
    replacements = {
        "<h3>": "",
        "</h3>": "\n",
        "<h4>": "",
        "</h4>": "\n",
        "<p>": "",
        "</p>": "\n",
        "<b>": "",
        "</b>": "",
        "<code>": "",
        "</code>": "",
        "<blockquote>": "«",
        "</blockquote>": "»\n",
        "<details>": "",
        "</details>": "\n",
        "<summary>": "",
        "</summary>": "\n",
        "<ul>": "",
        "</ul>": "",
        "<li>": "• ",
        "</li>": "\n",
        "<table>": "",
        "</table>": "\n",
        "<tr>": "",
        "</tr>": "\n",
        "<th>": "",
        "</th>": " | ",
        "<td>": "",
        "</td>": " | ",
    }
    text = rich_html
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.strip()


async def send_rich_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    rich_html: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None,
) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN")

    payload: dict[str, Any] = {"chat_id": chat_id, "rich_message": {"html": rich_html}}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup.to_dict()

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(f"https://api.telegram.org/bot{token}/sendRichMessage", json=payload)
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(str(body))
    except Exception:
        logger.exception("sendRichMessage failed, using fallback send_message")
        await context.bot.send_message(
            chat_id=chat_id,
            text=flatten_rich_text(rich_html),
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["session"] = CallSession(call_id=next_call_id(), started_at=now_label())
    await send_rich_message(context, update.effective_chat.id, format_rich_intro(), reply_markup=build_main_keyboard())
    await send_current_step(update, context)


async def new_call(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("session", None)
    await send_rich_message(
        context,
        update.effective_chat.id,
        "<h3>🛑 Звонок сброшен</h3><p>Нажми «🚀 Начать звонок», чтобы начать заново.</p>",
        reply_markup=build_main_keyboard(),
    )


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.user_data.get("session")
    if session is None:
        calls = load_today_calls()
        await send_rich_message(
            context,
            update.effective_chat.id,
            format_today_summary_rich(),
            reply_markup=build_today_calls_keyboard(calls) if calls else build_main_keyboard(),
        )
        return

    await send_rich_message(
        context,
        update.effective_chat.id,
        format_current_summary_rich(session),
        reply_markup=build_main_keyboard(),
    )


async def today_calls(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    calls = load_today_calls()
    await send_rich_message(
        context,
        update.effective_chat.id,
        format_today_summary_rich(),
        reply_markup=build_today_calls_keyboard(calls) if calls else build_main_keyboard(),
    )


async def send_current_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = get_session(context)

    if session.step_index >= TOTAL_STEPS:
        session.finished = True
        await send_rich_message(
            context,
            update.effective_chat.id,
            "<h3>🎯 Вопросы закончились</h3><p>Выбери итог разговора.</p>",
            reply_markup=build_result_keyboard(),
        )
        return

    step = SCRIPT_STEPS[session.step_index]
    reply_markup = build_step_keyboard(step["prompt"], session.step_index) if step["expects_note"] else build_greeting_keyboard(step["prompt"])
    await send_rich_message(context, update.effective_chat.id, format_step_rich(session.step_index), reply_markup=reply_markup)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    text = update.message.text.strip()

    if text in {"🚀 Начать звонок", "/start"}:
        await start(update, context)
        return
    if text in {"🔄 Новый звонок", "/newcall"}:
        await new_call(update, context)
        return
    if text in {"📝 Сводка", "/summary"}:
        await summary(update, context)
        return
    if text in {"📚 Сегодня", "/today"}:
        await today_calls(update, context)
        return
    if text in {"🛑 Сбросить", "/cancel"}:
        await cancel(update, context)
        return

    session = get_session(context)

    if session.waiting_for_decline_reason:
        session.decline_reason = text
        session.waiting_for_decline_reason = False
        session.finished = True
        save_completed_call(session)
        await send_rich_message(
            context,
            update.effective_chat.id,
            format_current_summary_rich(session, completed=True),
            reply_markup=build_main_keyboard(),
        )
        return

    if session.finished:
        await update.message.reply_text(
            "Этот звонок уже завершён. Нажми «🔄 Новый звонок», чтобы начать следующий.",
            reply_markup=build_main_keyboard(),
        )
        return

    step = SCRIPT_STEPS[session.step_index]
    if not step["expects_note"]:
        await update.message.reply_text("На этом шаге просто нажми «➡️ Дальше».")
        return

    session.notes.append((step["field"], text))
    session.step_index += 1
    await send_current_step(update, context)


async def handle_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return

    await query.answer()
    session = get_session(context)

    if query.data == "next_step":
        if not session.finished and session.step_index < TOTAL_STEPS:
            session.step_index += 1
        await send_current_step(update, context)
        return

    if query.data.startswith("skip:"):
        if session.finished:
            return
        _, raw_index = query.data.split(":", 1)
        if int(raw_index) != session.step_index:
            await send_current_step(update, context)
            return
        step = SCRIPT_STEPS[session.step_index]
        session.notes.append((step["field"], "Пропущено"))
        session.step_index += 1
        await send_current_step(update, context)
        return

    if query.data.startswith("open_call:"):
        _, raw_call_id = query.data.split(":", 1)
        if not raw_call_id.isdigit():
            return
        payload = find_call_payload(int(raw_call_id))
        if payload is None:
            await query.message.reply_text("Не нашёл этот звонок.")
            return
        calls = load_today_calls()
        await send_rich_message(
            context,
            update.effective_chat.id,
            format_saved_call_rich(payload),
            reply_markup=build_today_calls_keyboard(calls) if calls else build_main_keyboard(),
        )
        return

    if query.data == "finish_early":
        session.finished = True
        await send_rich_message(
            context,
            update.effective_chat.id,
            "<h3>🛑 Звонок завершён раньше</h3><p>Выбери итог разговора.</p>",
            reply_markup=build_result_keyboard(),
        )
        return

    if query.data == "agree":
        session.agreed = True
        session.finished = True
        save_completed_call(session)
        await send_rich_message(
            context,
            update.effective_chat.id,
            format_current_summary_rich(session, completed=True),
            reply_markup=build_main_keyboard(),
        )
        return

    if query.data == "decline":
        session.agreed = False
        session.waiting_for_decline_reason = True
        await update.effective_chat.send_message("❌ Напиши причину отказа одним сообщением.", reply_markup=build_main_keyboard())


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception while processing update", exc_info=context.error)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN")

    asyncio.set_event_loop(asyncio.new_event_loop())

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("newcall", new_call))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("summary", summary))
    application.add_handler(CommandHandler("today", today_calls))
    application.add_handler(CallbackQueryHandler(handle_decision))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(handle_error)

    logger.info("Bot is running")
    application.run_polling()


if __name__ == "__main__":
    main()
