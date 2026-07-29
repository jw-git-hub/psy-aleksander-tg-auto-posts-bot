#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Установка Telegram-бота Александр Красногор ==="

# Создаём venv если нет
if [ ! -d "venv" ]; then
    echo "Создаю виртуальное окружение..."
    python3 -m venv venv
fi

# Устанавливаем зависимости
echo "Устанавливаю зависимости..."
./venv/bin/pip install -r requirements.txt --quiet

# Создаём директорию логов
mkdir -p logs

# Создаём posted-topics.json если нет
if [ ! -f "posted-topics.json" ]; then
    echo "[]" > posted-topics.json
fi

# Права доступа: .env/config.json содержат токены (Telegram/FB/IG) — не должны
# быть world-readable. logs/ и её содержимое — тоже (там могут оставаться
# нередактированные фрагменты старых записей).
chmod 600 .env config.json 2>/dev/null || true
chmod 700 logs
chmod 600 logs/*.log* 2>/dev/null || true

echo ""
echo "=== Установка завершена ==="
echo ""
echo "Добавьте в cron (сервер в UTC, Бангкок UTC+7):"
echo "  crontab -e"
echo ""
echo "  # 10:00 Бангкок = 03:00 UTC"
echo "  0 3 * * * $SCRIPT_DIR/run_with_retry.sh >> $SCRIPT_DIR/logs/cron.log 2>&1"
echo ""
echo "  # 18:00 Бангкок = 11:00 UTC"
echo "  0 11 * * * $SCRIPT_DIR/run_with_retry.sh >> $SCRIPT_DIR/logs/cron.log 2>&1"
echo ""
echo "Тест: ./venv/bin/python3 post_bot.py"
