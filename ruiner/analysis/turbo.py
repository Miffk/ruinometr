"""Турбо-нормы: свежие турбо-матчи с тем же героем на том же ранге.

Про в турбо не играют, а нормы OpenDota (benchmarks) собраны без учёта режима, поэтому для турбо
собираем свою выборку: SQL-обозреватель OpenDota находит матчи, а по каждому матчу без разбора реплея
OpenDota отдаёт итоговую статистику, предметы в конце игры и прокачку. Таймингов покупок там нет —
их оцениваем по таймингам про, умноженным на темп турбо (во сколько раз быстрее герой копит золото).
"""

import time
from bisect import bisect_left, bisect_right
from statistics import median

from ..constants import Constants
from ..opendota import OpenDota, OpenDotaError
from .core import clamp, fmt_time
from .items import BOOTS, CORE_SHARE, MIN_SAMPLES, OFFMETA_SHARE, _components, _owned_at, first_purchases

TURBO_MODE = 23
# «Поздно» в турбо: оценка тайминга не раньше 5 минут, предмет у турбо-игроков хотя бы в 30% игр,
# и куплен позже оценки × 1.5 + 2 минуты.
LATE_MIN_SHARE = 0.3
LATE_MIN_EST = 300
LATE_FACTOR = 1.5
LATE_SLACK = 120
MIN_DURATION = 15 * 60          # короче — обычно ливы и ранние гг, норм не дают
POOL_QUERY_TTL = 12 * 3600
MATCHES_PER_HERO_QUERY = 60
METRICS = {
    "gold_per_min": lambda p, m: p.get("gold_per_min"),
    "xp_per_min": lambda p, m: p.get("xp_per_min"),
    "last_hits_per_min": lambda p, m: (p.get("last_hits") or 0) / m,
    "hero_damage_per_min": lambda p, m: (p.get("hero_damage") or 0) / m,
    "tower_damage": lambda p, m: p.get("tower_damage") or 0,
    "hero_healing_per_min": lambda p, m: (p.get("hero_healing") or 0) / m,
    "deaths_per_min": lambda p, m: (p.get("deaths") or 0) / m,
}


def _rank_band(rank_tiers: list) -> tuple[int, int] | None:
    tiers = [int(r) for r in rank_tiers if r]
    if not tiers:
        return None
    medal = round(median(t // 10 for t in tiers))
    return medal * 10, medal * 10 + 9


async def _record(od: OpenDota, match_id: int, consts: Constants) -> dict | None:
    name = f"turbo_{match_id}"
    rec = od.read_cache(name, None)
    if rec is not None:
        return rec or None
    try:
        m = await od.match(match_id, cache=False)
    except OpenDotaError:
        return None
    if m.get("game_mode") != TURBO_MODE or not m.get("players"):
        od.write_cache(name, {})
        return None
    minutes = max((m.get("duration") or 0) / 60, 1)
    rec = {
        "match_id": match_id, "duration": m.get("duration"),
        "players": [{
            "hero_id": p.get("hero_id"),
            "win": bool(p.get("win")),
            "left": bool(p.get("leaver_status")) or bool(p.get("abandons")),
            "metrics": {k: f(p, minutes) for k, f in METRICS.items()},
            "items": [k for k in (consts.item_key_by_id.get(p.get(s)) for s in
                                  ("item_0", "item_1", "item_2", "item_3", "item_4", "item_5",
                                   "backpack_0", "backpack_1", "backpack_2")) if k],
            "shard": bool(p.get("aghanims_shard")),
            "skills": p.get("ability_upgrades_arr") or [],
        } for p in m["players"]],
    }
    od.write_cache(name, rec)
    return rec


async def load_pool(od: OpenDota, hero_ids: list[int], rank_tiers: list, consts: Constants,
                    per_hero: int, progress=None) -> dict:
    """Выборка турбо-игроков по каждому герою матча. Возвращает {hero_id: [сэмплы]} и описание выборки."""
    band = _rank_band(rank_tiers)
    samples: dict[int, list] = {h: [] for h in hero_ids}
    seen: set[int] = set()
    for i, hero in enumerate(hero_ids):
        if progress:
            progress(f"Собираем турбо-нормы: {consts.hero_name(hero)} ({i + 1}/{len(hero_ids)})")
        rows = []
        for widen in (0, 10):
            if band:
                lo, hi = band[0] - widen, band[1] + widen
                rank_sql = f"AND avg_rank_tier BETWEEN {lo} AND {hi}"
            else:
                rank_sql = ""
            sql = (f"SELECT match_id FROM public_matches WHERE game_mode = {TURBO_MODE} AND duration >= {MIN_DURATION} "
                   f"{rank_sql} AND ({hero} = ANY(radiant_team) OR {hero} = ANY(dire_team)) "
                   f"ORDER BY match_id DESC LIMIT {MATCHES_PER_HERO_QUERY}")
            try:
                rows = await od.explorer(sql, f"turbo_q_{hero}_{band}_{widen}", POOL_QUERY_TTL)
            except OpenDotaError:
                rows = []
            if len(rows) >= per_hero:
                break
        for row in rows:
            if len(samples[hero]) >= per_hero:
                break
            mid = row["match_id"]
            rec = await _record(od, mid, consts)
            if not rec or mid in seen:
                continue
            seen.add(mid)
            # Матч добавляет сэмплы всем героям нашего матча, которые в нём есть.
            for p in rec["players"]:
                if p["hero_id"] in samples and not p["left"] and len(samples[p["hero_id"]]) < per_hero:
                    samples[p["hero_id"]].append({**p, "match_id": mid, "duration": rec["duration"]})
    return {"samples": samples, "band": band, "built_at": time.time()}


def benchmarks(player: dict, duration: int, hero_samples: list) -> dict:
    """Как benchmarks OpenDota, только по турбо-выборке: {метрика: {raw, pct}}."""
    minutes = max(duration / 60, 1)
    out = {}
    for name, f in METRICS.items():
        values = sorted(s["metrics"][name] for s in hero_samples if s["metrics"].get(name) is not None)
        raw = f(player, minutes)
        if len(values) < MIN_SAMPLES or raw is None:
            continue
        # доля сэмплов ниже значения (середина при равенстве) — как percentile rank
        lo, hi = bisect_left(values, raw), bisect_right(values, raw)
        out[name] = {"raw": raw, "pct": (lo + hi) / 2 / len(values), "n": len(values)}
    return out


def pace(hero_samples: list, normal_bench: dict | None) -> float | None:
    """Во сколько раз быстрее герой копит золото в турбо: медиана GPM в обычных играх / в турбо."""
    gpm = [s["metrics"]["gold_per_min"] for s in hero_samples if s["metrics"].get("gold_per_min")]
    normal = None
    for row in ((normal_bench or {}).get("result") or {}).get("gold_per_min") or []:
        if abs(row.get("percentile", 0) - 0.5) < 1e-6:
            normal = row.get("value")
    if len(gpm) < MIN_SAMPLES or not normal:
        return None
    return clamp(normal / median(gpm), 0.35, 0.9)


def compare_build_turbo(player: dict, duration: int, hero_samples: list, pro_meta: dict | None,
                        hero_pace: float, consts: Constants) -> dict:
    """Состав сборки — против турбо-игроков того же героя; тайминги — оценка: тайминги про × темп турбо."""
    first = first_purchases(player.get("purchase_log"))
    final = {consts.item_key_by_id.get(player.get(s)) for s in
             ("item_0", "item_1", "item_2", "item_3", "item_4", "item_5", "backpack_0", "backpack_1", "backpack_2")}
    owned = dict(first)
    for k in final:
        if k and k not in owned:
            owned[k] = None
    bought = sorted(((k, t) for k, t in owned.items() if consts.is_key_item(k)), key=lambda kt: (kt[1] is None, kt[1] or 0))
    keys = {k for k, _ in bought}
    bought = [(k, t) for k, t in bought if not any(k in _components(o, consts) for o in keys if o != k)]

    # Похожие по длине турбо-игры: от 70% до 140% длины нашего матча.
    similar = [s for s in hero_samples if 0.7 * duration <= s["duration"] <= 1.4 * duration] or hero_samples
    n = len(similar)
    share = {}
    for s in similar:
        items = set(s["items"]) | ({"aghanims_shard"} if s.get("shard") else set())
        for k in items:
            if consts.is_key_item(k):
                share[k] = share.get(k, 0) + 1
    share = {k: v / n for k, v in share.items()} if n else {}

    pro_times = {}
    for s in (pro_meta or {}).get("samples") or []:
        for k, t in s["first"].items():
            pro_times.setdefault(k, []).append(t)
    est = {k: median(v) * hero_pace for k, v in pro_times.items() if v}

    result = {
        "available": n >= MIN_SAMPLES, "turbo": True, "pace": round(hero_pace, 2),
        "samples": n, "basis": "turbo", "popularity": [], "pro_examples": [],
        "timeline": [], "core": [], "missing": [], "late": [], "offmeta": [], "score": None,
    }
    for k, t in bought:
        entry = {**consts.item_ref(k), "time": t, "time_fmt": fmt_time(t) if t is not None else "—", "status": "unknown"}
        sh = share.get(k, 0)
        if n >= MIN_SAMPLES and sh < OFFMETA_SHARE and k not in BOOTS:
            entry["status"] = "offmeta"
            result["offmeta"].append(entry)
        elif k in est and t is not None:
            entry["pro_median"] = est[k]
            entry["pro_median_fmt"] = fmt_time(est[k])
            entry["pro_share"] = round(sh * 100)
            # Оценка грубая, поэтому «поздно» — только с большим запасом и только для предметов,
            # которые турбо-игроки правда собирают, и не для ранних дешёвых (их покупают на стартовое золото).
            if (sh >= LATE_MIN_SHARE and est[k] >= LATE_MIN_EST
                    and t > est[k] * LATE_FACTOR + LATE_SLACK):
                entry["status"] = "late"
                result["late"].append(entry)
            elif t < est[k] * 0.85:
                entry["status"] = "early"
            else:
                entry["status"] = "on_time"
        elif sh >= OFFMETA_SHARE:
            entry["status"] = "on_time"
        result["timeline"].append(entry)

    if not result["available"]:
        return result
    core = sorted(((k, v) for k, v in share.items() if v >= CORE_SHARE), key=lambda kv: est.get(kv[0], 1e9))
    for k, v in core:
        t = _owned_at(k, first, consts)
        if t is None and k in final:
            t = duration
        result["core"].append({**consts.item_ref(k), "share": round(v * 100), "median": est.get(k),
                               "median_fmt": fmt_time(est[k]) if k in est else "—",
                               "bought_at": t, "bought_fmt": fmt_time(t) if t is not None else None})
    core_keys = {k for k, _ in core}
    for k, v in core:
        if v < 0.6 or _owned_at(k, first, consts) is not None or k in final:
            continue
        if any(k in _components(o, consts) for o in core_keys if o != k and _owned_at(o, first, consts) is None):
            continue
        if k in est and est[k] + 180 * hero_pace >= duration:
            continue
        result["missing"].append({**consts.item_ref(k), "share": round(v * 100),
                                  "median": est.get(k, duration), "median_fmt": fmt_time(est[k]) if k in est else "—"})
    parts = []
    for k, v in core:
        t = _owned_at(k, first, consts)
        if t is None and k in final:
            t = duration
        if t is None:
            parts.append(0.0)
        elif k in est and t > est[k] * 1.3:
            parts.append(clamp(1 - (t - est[k] * 1.3) / (900 * hero_pace), 0.3, 1.0))
        else:
            parts.append(1.0)
    if parts:
        result["score"] = sum(parts) / len(parts)
    return result


def skills_meta(hero_samples: list) -> dict:
    """Сэмплы в формате меты про, чтобы переиспользовать сравнение прокачки."""
    return {"samples": [{"skills": s["skills"], "pos": None} for s in hero_samples if s.get("skills")]}
