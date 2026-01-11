# Ira Finance Bot (Telegram)

Бот для фиксации расходов/доходов (только для одного пользователя) + анализ (сегодня/месяц/год).
Хранение данных — Google Sheets через Google Apps Script Web App.

## Переменные окружения (Railway Variables)

- BOT_TOKEN=...
- SCRIPT_URL=... (URL Google Apps Script Web App)
- WIFE_TG_ID=123456789
- WEBHOOK_URL=https://xxxxx.up.railway.app   (рекомендуется для Railway)
- PORT=8080 (Railway задаёт сам)

## Как деплоить на Railway (с нуля)

1) Создай новый проект Railway → Deploy from GitHub repo
2) Добавь переменные окружения из списка выше
3) Дождись деплоя
4) Скопируй домен Railway (Settings → Domains) и вставь в WEBHOOK_URL
5) Redeploy (после установки WEBHOOK_URL бот сам поставит webhook)

## Локальный запуск (опционально)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export BOT_TOKEN=...
export SCRIPT_URL=...
export WIFE_TG_ID=...

python main.py
