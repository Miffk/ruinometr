"""Клиент OpenDota API с дисковым кэшем и ограничением частоты запросов."""

import asyncio
import json
import time
from pathlib import Path

import httpx

BASE_URL = "https://api.opendota.com/api"


class OpenDotaError(Exception):
    pass


class MatchNotFound(OpenDotaError):
    pass


def is_parsed(match: dict | None) -> bool:
    """Матч разобран, если OpenDota прошёл реплей: есть version и логи покупок."""
    if not match or match.get("version") is None:
        return False
    players = match.get("players") or []
    return bool(players) and all(p.get("purchase_log") is not None for p in players)


class OpenDota:
    def __init__(self, cache_dir: Path, api_key: str | None = None, min_interval: float = 1.05):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key
        self.min_interval = 0.0 if api_key else min_interval
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._client = httpx.AsyncClient(timeout=90, headers={"User-Agent": "ruiner-local/0.1"})

    async def close(self):
        await self._client.aclose()

    # --- кэш ---

    def _cache_path(self, name: str) -> Path:
        return self.cache_dir / f"{name}.json"

    def read_cache(self, name: str, ttl: float | None):
        path = self._cache_path(name)
        if not path.exists():
            return None
        if ttl is not None and time.time() - path.stat().st_mtime > ttl:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write_cache(self, name: str, data) -> None:
        path = self._cache_path(name)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    # --- HTTP ---

    async def request(self, method: str, path: str, params: dict | None = None):
        params = dict(params or {})
        if self.api_key:
            params["api_key"] = self.api_key
        last_error = None
        for attempt in range(4):
            async with self._lock:
                wait = self._last_request + self.min_interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request = time.monotonic()
            try:
                r = await self._client.request(method, BASE_URL + path, params=params)
            except httpx.HTTPError as e:
                last_error = e
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 404:
                raise MatchNotFound(path)
            if r.status_code == 429 or r.status_code >= 500:
                last_error = OpenDotaError(f"HTTP {r.status_code} на {path}")
                await asyncio.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        raise OpenDotaError(f"OpenDota не ответил на {path}: {last_error}")

    async def cached(self, name: str, ttl: float | None, path: str, params: dict | None = None):
        data = self.read_cache(name, ttl)
        if data is not None:
            return data
        data = await self.request("GET", path, params)
        self.write_cache(name, data)
        return data

    # --- эндпоинты ---

    async def match(self, match_id: int, cache: bool = True) -> dict:
        """Матч целиком. Разобранный матч не меняется, поэтому кэшируем навсегда."""
        name = f"match_{match_id}"
        if cache:
            data = self.read_cache(name, None)
            if data is not None:
                return data
        data = await self.request("GET", f"/matches/{match_id}")
        if not data or "players" not in data:
            raise MatchNotFound(str(match_id))
        if cache and is_parsed(data):
            self.write_cache(name, data)
        return data

    async def request_parse(self, match_id: int):
        return await self.request("POST", f"/request/{match_id}")

    async def constants(self, resource: str):
        return await self.cached(f"const_{resource}", 7 * 86400, f"/constants/{resource}")

    async def item_popularity(self, hero_id: int):
        """Популярность предметов героя по стадиям — OpenDota считает её по про-матчам."""
        return await self.cached(f"itempop_{hero_id}", 86400, f"/heroes/{hero_id}/itemPopularity")

    async def explorer(self, sql: str, cache_name: str, ttl: float | None):
        """SQL к базе OpenDota (только чтение). Тяжёлые агрегаты там падают по таймауту — считаем у себя."""
        data = await self.cached(cache_name, ttl, "/explorer", {"sql": sql})
        if data.get("err"):
            raise OpenDotaError(f"explorer: {data['err']}")
        return data.get("rows") or []

    async def hero_benchmarks(self, hero_id: int):
        return await self.cached(f"bench_{hero_id}", 7 * 86400, "/benchmarks", {"hero_id": hero_id})

    async def hero_pro_matches(self, hero_id: int):
        """Свежие матчи лиг (про-сцена) на герое."""
        return await self.cached(f"heromatches_{hero_id}", 6 * 3600, f"/heroes/{hero_id}/matches")
