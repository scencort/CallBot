# CallBot

Telegram-бот для ведения звонка по скрипту продажи квартиры.

## Что умеет

- запускает сценарий командой `/start`
- показывает вопросы по порядку
- после каждого вопроса принимает заметку одним сообщением
- ведёт журнал завершённых звонков
- показывает список звонков за день
- открывает детальную карточку звонка по кнопке из сводки

## Локальный запуск

```bash
pip install -r requirements.txt
pip install --upgrade -r requirements.txt
```

Задай токен:

```bash
export TELEGRAM_BOT_TOKEN=your_token_here
```

И запусти:

```bash
python bot.py
```

## Деплой на сервер

Готовые файлы:

- [deploy/SERVER.md](/C:/Users/yaros/Desktop/CallBot/deploy/SERVER.md)
- [deploy/install_server.sh](/C:/Users/yaros/Desktop/CallBot/deploy/install_server.sh)
- [deploy/call_bot.service](/C:/Users/yaros/Desktop/CallBot/deploy/call_bot.service)

Целевая папка сервера: `/opt/call_bot`

Быстрый запуск на сервере:

```bash
sudo bash deploy/install_server.sh
sudo nano /opt/call_bot/.env
sudo systemctl start call_bot
sudo systemctl status call_bot
```
