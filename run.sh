#!/usr/bin/env sh
# Запуск локального Ruiner на Linux/macOS: http://127.0.0.1:8000
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
# Свой парсер реплеев. Без него разбор работает, но без AFK, карты и сигналов из реплея.
if [ ! -f parser/target/ruiner-parser.jar ]; then
  if command -v java >/dev/null 2>&1; then
    echo "Собираю парсер реплеев, первый раз это пара минут..."
    sh parser/mvnw -q -f parser/pom.xml package -DskipTests
  else
    echo "Java не найдена: парсер реплеев не собран, разбор пойдёт без него. Нужен JDK 21+."
  fi
fi
exec .venv/bin/python -m uvicorn ruiner.app:app --host 127.0.0.1 --port 8000
