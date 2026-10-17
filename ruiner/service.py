"""Фоновые задачи разбора: дождаться разбора реплея в OpenDota, загрузить мету героев, собрать отчёт."""

import asyncio
import re
import time
from dataclasses import dataclass, field

from .analysis import turbo as turbo_mod
from .analysis.items import load_hero_meta
from .analysis.mode import is_turbo_match
from .analysis.report import build_report
from .config import ANALYSIS_VERSION, PRO_SAMPLES_PER_HERO, TURBO_SAMPLES_PER_HERO
from .constants import Constants, load_constants
from .opendota import MatchNotFound, OpenDota, OpenDotaError, is_parsed
from .replay import ReplayUnavailable, parse_replay

PARSE_POLL_SECONDS = 10
PARSE_TIMEOUT_SECONDS = 15 * 60

MATCH_ID_RE = re.compile(r"(\d{8,12})")


def extract_match_id(text: str) -> int | None:
    """ID матча из числа или ссылки Dotabuff/OpenDota/Stratz."""
    m = MATCH_ID_RE.search(text or "")
    return int(m.group(1)) if m else None


@dataclass
class Job:
    match_id: int
    state: str = "queued"
    message: str = "В очереди"
    progress: float = 0.0
    error: str | None = None
    result: dict | None = None
    started_at: float = field(default_factory=time.time)

    def view(self) -> dict:
        return {"match_id": self.match_id, "state": self.state, "message": self.message,
                "progress": round(self.progress, 2), "error": self.error}


class AnalysisService:
    def __init__(self, od: OpenDota):
        self.od = od
        self.jobs: dict[int, Job] = {}
        self._consts: Constants | None = None
        self._tasks: set[asyncio.Task] = set()

    async def constants(self) -> Constants:
        if self._consts is None:
            self._consts = await load_constants(self.od)
        return self._consts

    def _report_cache_name(self, match_id: int) -> str:
        return f"report_{match_id}_v{ANALYSIS_VERSION}_{PRO_SAMPLES_PER_HERO}"

    def get(self, match_id: int, refresh: bool = False) -> Job:
        job = self.jobs.get(match_id)
        if job and not refresh and job.state != "error":
            return job
        job = Job(match_id)
        if not refresh:
            cached = self.od.read_cache(self._report_cache_name(match_id), None)
            if cached is not None:
                job.state, job.message, job.progress, job.result = "done", "Готово", 1.0, cached
                self.jobs[match_id] = job
                return job
        self.jobs[match_id] = job
        task = asyncio.create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: Job) -> None:
        try:
            job.state, job.message, job.progress = "fetch", "Загружаем матч из OpenDota", 0.05
            match = await self.od.match(job.match_id)
            if not is_parsed(match):
                match = await self._wait_for_parse(job)
            consts = await self.constants()

            # Этап 2: свой разбор реплея. Если не вышло — разбор всё равно строим, без AFK и порядочности.
            job.state, job.progress = "replay", 0.25
            parsed, replay_reason = None, None
            try:
                parsed = await parse_replay(match, progress=lambda msg: setattr(job, "message", msg))
            except ReplayUnavailable as e:
                replay_reason = str(e)

            heroes = sorted({p["hero_id"] for p in match["players"]})
            metas = {}
            for i, hero_id in enumerate(heroes):
                job.state = "meta"
                job.message = f"Собираем закуп про-игроков: {consts.hero_name(hero_id)} ({i + 1}/{len(heroes)})"
                job.progress = 0.35 + 0.6 * i / len(heroes)
                try:
                    metas[hero_id] = await load_hero_meta(self.od, hero_id, PRO_SAMPLES_PER_HERO)
                except OpenDotaError:
                    metas[hero_id] = None

            turbo = None
            if is_turbo_match(match):
                turbo = await self._turbo_reference(job, match, heroes, consts)

            job.state, job.message, job.progress = "build", "Собираем разбор", 0.97
            report = build_report(match, consts, metas, parsed, replay_reason, turbo)
            self.od.write_cache(self._report_cache_name(job.match_id), report)
            job.result = report
            job.state, job.message, job.progress = "done", "Готово", 1.0
        except MatchNotFound:
            job.state, job.error = "error", "Матч не найден в OpenDota. Проверьте ID."
        except OpenDotaError as e:
            job.state, job.error = "error", f"OpenDota недоступен: {e}"
        except Exception as e:  # покажем ошибку на странице, а не молча зависнем
            job.state, job.error = "error", f"Ошибка разбора: {type(e).__name__}: {e}"
            raise

    async def _turbo_reference(self, job: Job, match: dict, heroes: list[int], consts: Constants) -> dict:
        """Турбо-выборка по героям матча и темп турбо для каждого героя."""
        job.state, job.progress = "turbo", 0.9

        def progress(msg):
            job.message = msg

        pool = await turbo_mod.load_pool(self.od, heroes, [p.get("rank_tier") for p in match["players"]], consts,
                                         TURBO_SAMPLES_PER_HERO, progress)
        paces = {}
        for hero_id in heroes:
            try:
                bench = await self.od.hero_benchmarks(hero_id)
            except OpenDotaError:
                bench = None
            paces[hero_id] = turbo_mod.pace(pool["samples"].get(hero_id) or [], bench)
        return {"pool": pool, "paces": paces}

    async def _wait_for_parse(self, job: Job) -> dict:
        job.state, job.message, job.progress = "parsing", "OpenDota скачивает и разбирает реплей", 0.1
        await self.od.request_parse(job.match_id)
        deadline = time.time() + PARSE_TIMEOUT_SECONDS
        while time.time() < deadline:
            await asyncio.sleep(PARSE_POLL_SECONDS)
            match = await self.od.match(job.match_id)
            if is_parsed(match):
                return match
            waited = PARSE_TIMEOUT_SECONDS - (deadline - time.time())
            job.progress = 0.1 + 0.2 * waited / PARSE_TIMEOUT_SECONDS
        raise OpenDotaError(
            "реплей так и не разобрался. Реплеи хранятся у Valve ограниченное время, "
            "матчи с ботами и часть лобби не записываются. Попробуйте позже."
        )
