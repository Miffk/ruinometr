"""Сигналы из своего разбора реплея: AFK по приказам, таблица после смерти, порядочность и вежливость, чат."""

import math
import re

from .core import fmt_time

# Сколько секунд подряд без приказов (пока герой жив) считаем отходом от игры.
AFK_MIN_SECONDS = 90
# Если за отрезок AFK герой сместился меньше этого (в единицах карты), считаем, что он стоял на месте.
STOOD_STILL_UNITS = 300

# Уровни из CDOTA_PlayerResource → полосы шкалы 0–12 000 из «Отчёта о порядочности» клиента.
# Подтверждено сверкой с battlepass.ru на матче 9046870406; остальные уровни показываем номером.
BEHAVIOR_BANDS = {4: "10 000+"}
COMM_BANDS = {7: "10 000+", 6: "8 000–10 000"}

# Грубый фильтр мата и оскорблений в чате «всем».
TOXIC_RE = re.compile(
    r"(х[уy][йеёяию]|п[иi]зд|(?<![а-яё])(за|у|вы|при|до|на|от|по|про|разъ|съ|въ|подъ)?[её]б[аеиоуы]|"
    r"бля|(?<![а-яё])сук[аи]|муд[ао]к|д[еи]бил|(?<![а-яё])даун|п[ие]д[оа]р|"
    r"\bnoob|\bfuck|\bshit|\bidiot|\bretard|\bkys\b|\bnigg|\bbitch)",
    re.IGNORECASE,
)


def _norm_hero(name: str | None) -> str:
    if not name:
        return ""
    return name.replace("CDOTA_Unit_Hero_", "").replace("npc_dota_hero_", "").replace("_", "").lower()


def map_players(parsed: dict, match: dict) -> dict[int, dict]:
    """player_slot OpenDota → игрок из реплея. В реплее игроки идут 0..9: сначала Свет, потом Тьма."""
    by_slot = {}
    for rp in parsed.get("players") or []:
        i = rp["index"]
        slot = i if i < 5 else 128 + (i - 5)
        by_slot[slot] = rp
    return by_slot


def _alive_runs(samples: list, start: float, end: float) -> list[tuple[float, float]]:
    """Отрезки внутри [start, end], когда герой был жив (по выборкам раз в секунду)."""
    runs = []
    cur = None
    for t, _x, _y, alive, *_ in samples:
        if t is None or t < start or t > end:
            continue
        if alive and cur is None:
            cur = t
        elif not alive and cur is not None:
            runs.append((cur, t))
            cur = None
    if cur is not None:
        runs.append((cur, end))
    return runs


def _displacement(samples: list, start: float, end: float) -> float:
    pts = [(x, y) for t, x, y, alive, *_ in samples if t is not None and start <= t <= end and alive]
    if len(pts) < 2:
        return 0.0
    x0, y0 = pts[0]
    return max(math.hypot(x - x0, y - y0) for x, y in pts)


def afk_windows(rp: dict, duration: int) -> list[dict]:
    orders = sorted(t for t in rp.get("orders") or [] if t is not None and 0 <= t <= duration)
    samples = rp.get("samples") or []
    bounds = [0.0] + orders + [float(duration)]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a < AFK_MIN_SECONDS:
            continue
        for s, e in _alive_runs(samples, a, b):
            if e - s >= AFK_MIN_SECONDS:
                moved = _displacement(samples, s, e)
                out.append({"start": round(s), "end": round(e), "seconds": round(e - s),
                            "start_fmt": fmt_time(s), "end_fmt": fmt_time(e),
                            "duration_fmt": fmt_time(e - s), "stood_still": moved < STOOD_STILL_UNITS})
    return out


def _dead_windows(samples: list) -> list[tuple[float, float]]:
    out, cur = [], None
    for t, _x, _y, alive, *_ in samples:
        if t is None or t < 0:
            continue
        if not alive and cur is None:
            cur = t
        elif alive and cur is not None:
            out.append((cur, t))
            cur = None
    return out


def scoreboard(rp: dict) -> dict:
    """Открытия панели статистики (m_iStatsPanel): сколько раз всего и после скольких смертей её открывал."""
    opens = [t for t, v in rp.get("stats_panel") or [] if t is not None and t >= 0 and v]
    dead = _dead_windows(rp.get("samples") or [])
    deaths_with_tab = sum(1 for a, b in dead if any(a <= t <= b for t in opens))
    return {"opens": len(opens), "deaths": len(dead), "deaths_with_tab": deaths_with_tab}


def band(level: int | None, bands: dict) -> str | None:
    if level is None or level < 0:
        return None
    return bands.get(level, f"уровень {level}")


def toxic_messages(match: dict, slot: int) -> list[dict]:
    out = []
    for c in match.get("chat") or []:
        if c.get("type") == "chat" and c.get("player_slot") == slot and TOXIC_RE.search(c.get("key") or ""):
            out.append({"time": int(c.get("time", 0)), "time_fmt": fmt_time(c.get("time", 0)), "text": c.get("key")})
    return out


def player_conduct(rp: dict | None, match: dict, slot: int, duration: int) -> dict:
    toxic = toxic_messages(match, slot)
    if rp is None:
        return {"available": False, "toxic": toxic}
    return {
        "available": True,
        "behavior_level": rp.get("behavior_level"),
        "comm_level": rp.get("comm_level"),
        "behavior": band(rp.get("behavior_level"), BEHAVIOR_BANDS),
        "comm": band(rp.get("comm_level"), COMM_BANDS),
        "orders": len(rp.get("orders") or []),
        "afk": afk_windows(rp, duration),
        "scoreboard": scoreboard(rp),
        "toxic": toxic,
        "hero_check": _norm_hero(rp.get("hero_class")),
    }
