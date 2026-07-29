#!/usr/bin/env bash
export PATH="$HOME/.local/bin:$PATH"
# run_with_retry.sh — Run post_bot.py with up to 3 attempts, 60s delay between retries.
# All output appended to logs/cron.log.
#
# "Success" needs more than the exit code: post_bot.py's main() returns
# normally (implicit exit 0) even when nothing was published this run —
# empty candidate pool, no article matched any topic, or Telegram itself
# failed to send (see main(): those paths all `return` with no sys.exit()).
# So a run only counts as successful if the exit code is 0 AND the run's own
# output contains the marker line post_bot.py logs right after a real
# Telegram publish: "INFO Опубликовано: <topic> (цикл N)".

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$PROJECT_DIR/logs/cron.log"
LOG_MAX_BYTES=$((2 * 1024 * 1024))
MAX_ATTEMPTS=3
RETRY_DELAY=60
PUBLISH_MARKER='INFO Опубликовано: '

cd "$PROJECT_DIR" || { echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] Cannot cd to $PROJECT_DIR" >> "$LOG_FILE"; exit 1; }
mkdir -p "$PROJECT_DIR/logs"  # создаём каталог логов на случай свежего клона до setup.sh

# Simple rotation: unlike post.log (logging.handlers.RotatingFileHandler,
# backupCount=2), cron.log is just >> appended to, so it grows forever.
# Keep at most one archive — ARM box, limited disk.
if [ -f "$LOG_FILE" ] && [ "$(stat -c %s "$LOG_FILE" 2>/dev/null || echo 0)" -gt "$LOG_MAX_BYTES" ]; then
    mv -f "$LOG_FILE" "${LOG_FILE}.1"
fi
# Keep the (possibly just-recreated) log file non-world-readable across rotations.
touch "$LOG_FILE"
chmod 600 "$LOG_FILE" 2>/dev/null || true

for attempt in $(seq 1 $MAX_ATTEMPTS); do
    echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] Attempt $attempt/$MAX_ATTEMPTS — starting post_bot.py" >> "$LOG_FILE"

    attempt_log="$(mktemp "$PROJECT_DIR/logs/.attempt.XXXXXX")"
    chmod 600 "$attempt_log" 2>/dev/null || true
    ./venv/bin/python3 post_bot.py > "$attempt_log" 2>&1
    exit_code=$?

    published=0
    if grep -qF "$PUBLISH_MARKER" "$attempt_log"; then
        published=1
    fi

    if [ $exit_code -eq 0 ] && [ $published -eq 1 ]; then
        # Успех: детальный вывод уже лежит в logs/post.log (RotatingFileHandler),
        # дублировать его в cron.log незачем — оставляем только строку публикации.
        grep -F "$PUBLISH_MARKER" "$attempt_log" >> "$LOG_FILE"
    else
        # Провал: полный вывод нужен для разбора — post.log мог не успеть записаться.
        cat "$attempt_log" >> "$LOG_FILE"
    fi
    rm -f "$attempt_log"

    if [ $exit_code -eq 0 ] && [ $published -eq 1 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] Attempt $attempt/$MAX_ATTEMPTS — success (exit 0, published)" >> "$LOG_FILE"
        exit 0
    fi

    if [ $exit_code -eq 0 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') [WARN] Attempt $attempt/$MAX_ATTEMPTS — exit 0 but nothing published, treating as failure" >> "$LOG_FILE"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') [WARN] Attempt $attempt/$MAX_ATTEMPTS — failed (exit $exit_code)" >> "$LOG_FILE"
    fi

    if [ $attempt -lt $MAX_ATTEMPTS ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] Waiting ${RETRY_DELAY}s before retry..." >> "$LOG_FILE"
        sleep $RETRY_DELAY
    fi
done

echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] All $MAX_ATTEMPTS attempts failed" >> "$LOG_FILE"
exit 1
