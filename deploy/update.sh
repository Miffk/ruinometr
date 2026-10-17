#!/usr/bin/env bash
# Обновить Руинометр на сервере до свежей версии с GitHub (запускать от root).
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/ruinometr}"
APP_USER="ruinometr"

GIT=(sudo -u "$APP_USER" git -C "$APP_DIR")
before="$("${GIT[@]}" rev-parse HEAD)"
"${GIT[@]}" pull --ff-only
after="$("${GIT[@]}" rev-parse HEAD)"
if [ "$before" = "$after" ]; then
  echo "Уже последняя версия."
  exit 0
fi

sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
# Парсер пересобираем, только если менялся его код.
if "${GIT[@]}" diff --name-only "$before" "$after" | grep -q '^parser/' && command -v javac >/dev/null 2>&1; then
  echo "Пересобираю парсер реплеев..."
  sudo -u "$APP_USER" env HOME="$APP_DIR" MAVEN_OPTS="-Xmx256m -XX:+UseSerialGC" \
    sh "$APP_DIR/parser/mvnw" -q -f "$APP_DIR/parser/pom.xml" package -DskipTests
fi
systemctl restart ruinometr
echo "Обновлено: $("${GIT[@]}" log --oneline -1)"
