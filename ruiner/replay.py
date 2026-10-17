"""Этап 2: скачать реплей с серверов Valve и прогнать через свой парсер (parser/, Java + clarity)."""

import asyncio
import json
import shutil
from pathlib import Path

import httpx

from .config import JAVA_BIN, PARSER_JAR, REPLAY_DIR

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
BZ2_MAGIC = b"BZh"
DEM_MAGIC = b"PBDEMS2"
PARSED_VERSION = 2


class ReplayUnavailable(Exception):
    """Реплей нельзя разобрать: нет Java/парсера, реплей удалён у Valve и т. п. Разбор продолжается без него."""


def parser_status() -> str | None:
    """None, если парсер готов, иначе — почему нет."""
    if not JAVA_BIN:
        return "не найдена Java — установите JDK 21+"
    if not PARSER_JAR.exists():
        return "парсер не собран — запустите run.bat или mvn package в папке parser"
    return None


def _decompress(src: Path, dst: Path) -> None:
    with src.open("rb") as f:
        magic = f.read(8)
    if magic.startswith(ZSTD_MAGIC):
        try:
            from compression import zstd  # Python 3.14+
            opener = zstd.open
        except ImportError:
            import zstandard  # для Python 3.12–3.13: pip install zstandard
            opener = zstandard.open
    elif magic.startswith(BZ2_MAGIC):
        import bz2
        opener = bz2.open
    elif magic.startswith(DEM_MAGIC):
        shutil.copyfile(src, dst)
        return
    else:
        raise ReplayUnavailable("неизвестный формат файла реплея")
    tmp = dst.with_suffix(".tmp")
    with opener(src, "rb") as fin, tmp.open("wb") as fout:
        shutil.copyfileobj(fin, fout, 1 << 20)
    tmp.replace(dst)


async def _download(url: str, dst: Path) -> None:
    tmp = dst.with_suffix(".part")
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=120), follow_redirects=True) as client:
        async with client.stream("GET", url) as r:
            if r.status_code == 404:
                raise ReplayUnavailable("реплея уже нет на серверах Valve (хранятся ограниченное время)")
            r.raise_for_status()
            with tmp.open("wb") as f:
                async for chunk in r.aiter_bytes(1 << 20):
                    f.write(chunk)
    tmp.replace(dst)


async def parse_replay(match: dict, progress=None) -> dict:
    """Вернуть разобранные данные реплея (кэшируются в data/replays/{id}.parsed.json)."""
    match_id = match["match_id"]
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    parsed_path = REPLAY_DIR / f"{match_id}.parsed.json"
    if parsed_path.exists():
        data = json.loads(parsed_path.read_text(encoding="utf-8"))
        if data.get("version") == PARSED_VERSION:
            return data

    reason = parser_status()
    if reason:
        raise ReplayUnavailable(reason)
    url = match.get("replay_url")
    if not url:
        raise ReplayUnavailable("OpenDota не знает ссылку на реплей")

    packed = REPLAY_DIR / f"{match_id}.dem.pack"
    dem = REPLAY_DIR / f"{match_id}.dem"
    try:
        if not dem.exists():
            if progress:
                progress("Скачиваем реплей с серверов Valve")
            await _download(url, packed)
            if progress:
                progress("Распаковываем реплей")
            await asyncio.to_thread(_decompress, packed, dem)
        if progress:
            progress("Разбираем реплей своим парсером")
        proc = await asyncio.create_subprocess_exec(
            JAVA_BIN, "-jar", str(PARSER_JAR), "parse", str(dem), str(parsed_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            tail = err.decode("utf-8", "replace").strip().splitlines()[-3:]
            raise ReplayUnavailable("парсер упал: " + " | ".join(tail))
    except httpx.HTTPError as e:
        raise ReplayUnavailable(f"не удалось скачать реплей: {e}") from e
    finally:
        # Реплей весит 30–60 МБ — после разбора храним только результат.
        for f in (packed, dem):
            f.unlink(missing_ok=True)
    return json.loads(parsed_path.read_text(encoding="utf-8"))
