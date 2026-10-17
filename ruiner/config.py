import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RUINER_DATA", ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"

# Чистка кэша: файлы старше N дней удаляются, и data/ не растёт больше лимита (для VPS с маленьким диском).
CACHE_MAX_AGE_DAYS = float(os.environ.get("RUINER_CACHE_DAYS", "30"))
CACHE_MAX_MB = float(os.environ.get("RUINER_CACHE_MAX_MB", "2000"))

# Без ключа OpenDota даёт ~60 запросов в минуту, поэтому держим паузу между запросами.
OPENDOTA_API_KEY = os.environ.get("OPENDOTA_API_KEY") or None
OPENDOTA_MIN_INTERVAL = float(os.environ.get("OPENDOTA_MIN_INTERVAL", "1.05"))

# Сколько свежих про-матчей на герое брать для сравнения закупа.
PRO_SAMPLES_PER_HERO = int(os.environ.get("RUINER_PRO_SAMPLES", "10"))

# Турбо: сколько турбо-игроков на героя (на вашем ранге) брать для норм и сравнения закупа.
TURBO_SAMPLES_PER_HERO = int(os.environ.get("RUINER_TURBO_SAMPLES", "15"))

# Этап 2: свой парсер реплеев (parser/, Java + clarity).
REPLAY_DIR = DATA_DIR / "replays"
PARSER_JAR = Path(os.environ.get("RUINER_PARSER_JAR", ROOT / "parser" / "target" / "ruiner-parser.jar"))
JAVA_BIN = os.environ.get("JAVA_BIN") or shutil.which("java")
# Флаги JVM для парсера: 160 МБ кучи хватает (проверено на 60-мегабайтном реплее), SerialGC и C1 экономят память.
PARSER_JAVA_OPTS = os.environ.get("RUINER_PARSER_JAVA_OPTS", "-Xmx160m -XX:+UseSerialGC -XX:TieredStopAtLevel=1 -Xss512k")

# Меняется при изменении логики разбора, чтобы не отдавать старый кэш.
ANALYSIS_VERSION = 14
