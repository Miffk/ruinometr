import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RUINER_DATA", ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"

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

# Меняется при изменении логики разбора, чтобы не отдавать старый кэш.
ANALYSIS_VERSION = 13
