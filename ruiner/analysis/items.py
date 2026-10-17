"""Закуп: мета героя по про-матчам и сравнение закупа игрока с ней."""

import time

from ..constants import Constants
from ..opendota import OpenDota, OpenDotaError, is_parsed
from .core import clamp, fmt_time, quantile, safe_median

META_TTL = 12 * 3600
# Формат сжатой записи про-матча; при изменении старые записи перезагружаются.
PRO_RECORD_VERSION = 2
UNPARSED_RETRY = 86400

# Сколько игр должно быть в выборке, чтобы сравнивать с ней.
MIN_SAMPLES = 3
# Сравниваем только с той же позицией, если таких игр не меньше этого числа, иначе — со всеми играми на герое.
MIN_POS_SAMPLES = 4
# Предмет считается «коровым» у про, если его берут хотя бы в такой доле игр.
CORE_SHARE = 0.4
# «Не собрал» говорим только про предметы, которые про берут почти всегда.
MISSING_SHARE = 0.6
# Ниже этой доли предмет у про редкий — покупка «вне меты».
OFFMETA_SHARE = 0.12
# Опоздание засчитываем, если позже 75-го процентиля про больше чем на 2 минуты и медианы — на 3.
LATE_OVER_P75 = 120
LATE_OVER_MEDIAN = 180
# «Поздно» говорим только про предметы, которые про берут хотя бы в такой доле игр.
LATE_MIN_SHARE = 0.3
# Ключевой предмет «не собран», если у про медиана хотя бы на 5 минут раньше конца матча.
MISSING_MARGIN = 300

# Сапоги взаимозаменяемы: если куплены любые из них, «без сапог» не говорим.
BOOTS = {"power_treads", "phase_boots", "arcane_boots", "tranquil_boots", "guardian_greaves",
         "boots_of_bearing", "travel_boots", "travel_boots_2"}

PHASES = [
    ("start_game_items", "Старт"),
    ("early_game_items", "Ранняя игра"),
    ("mid_game_items", "Мидгейм"),
    ("late_game_items", "Лейт"),
]


def first_purchases(purchase_log: list[dict] | None) -> dict[str, int]:
    first: dict[str, int] = {}
    for e in purchase_log or []:
        key = e.get("key")
        if not key or key.startswith("recipe_") or key in first:
            continue
        first[key] = int(e.get("time", 0))
    return first


async def _pro_record(od: OpenDota, match_id: int) -> dict | None:
    """Сжатая запись про-матча: герой, позиция, победа и первые покупки. Полный матч не храним."""
    name = f"pro_{match_id}"
    rec = od.read_cache(name, None)
    if rec is not None:
        if rec.get("unparsed"):
            if time.time() - rec.get("fetched_at", 0) < UNPARSED_RETRY:
                return None
        elif rec.get("version") == PRO_RECORD_VERSION:
            return rec
    try:
        m = await od.match(match_id, cache=False)
    except OpenDotaError:
        return None
    if not is_parsed(m):
        od.write_cache(name, {"unparsed": True, "fetched_at": time.time()})
        return None
    rec = {
        "version": PRO_RECORD_VERSION,
        "match_id": match_id,
        "duration": m.get("duration"),
        "start_time": m.get("start_time"),
        "players": [
            {
                "hero_id": p.get("hero_id"),
                "pos": p.get("position_est"),
                "win": bool(p.get("win")),
                "name": p.get("name") or p.get("personaname"),
                "first": first_purchases(p.get("purchase_log")),
                "skills": p.get("ability_upgrades_arr") or [],
            }
            for p in m.get("players", [])
        ],
    }
    od.write_cache(name, rec)
    return rec


async def load_hero_meta(od: OpenDota, hero_id: int, limit: int) -> dict:
    """Мета героя: популярность предметов по стадиям и первые покупки в свежих про-матчах."""
    cached = od.read_cache(f"meta_{hero_id}_{limit}_v{PRO_RECORD_VERSION}", META_TTL)
    if cached is not None:
        return cached

    try:
        popularity = await od.item_popularity(hero_id)
    except OpenDotaError:
        popularity = {}
    try:
        pro_matches = await od.hero_pro_matches(hero_id)
    except OpenDotaError:
        pro_matches = []

    samples = []
    for pm in pro_matches[: limit * 2]:
        if len(samples) >= limit:
            break
        rec = await _pro_record(od, pm["match_id"])
        if not rec:
            continue
        pl = next((p for p in rec["players"] if p["hero_id"] == hero_id), None)
        if not pl or not pl["first"]:
            continue
        samples.append({
            "match_id": rec["match_id"],
            "duration": rec["duration"],
            "start_time": rec["start_time"],
            "league": pm.get("league_name"),
            "pos": pl["pos"],
            "win": pl["win"],
            "name": pl["name"],
            "first": pl["first"],
            "skills": pl.get("skills") or [],
        })

    meta = {"hero_id": hero_id, "popularity": popularity, "samples": samples, "built_at": time.time()}
    od.write_cache(f"meta_{hero_id}_{limit}_v{PRO_RECORD_VERSION}", meta)
    return meta


def _pro_item_stats(meta: dict, pos: int, consts: Constants):
    samples = meta.get("samples") or []
    same_pos = [s for s in samples if s.get("pos") == pos]
    use = same_pos if len(same_pos) >= MIN_POS_SAMPLES else samples
    basis = "pos" if use is same_pos else "all"
    n = len(use)
    times: dict[str, list[int]] = {}
    for s in use:
        for key, t in s["first"].items():
            if consts.is_key_item(key):
                times.setdefault(key, []).append(t)
    stats = {
        key: {
            "share": len(ts) / n,
            "n": len(ts),
            "median": safe_median(ts),
            "p25": quantile(ts, 0.25),
            "p75": quantile(ts, 0.75),
        }
        for key, ts in times.items()
    } if n else {}
    return n, basis, use, stats


def _popularity_view(meta: dict, consts: Constants) -> list[dict]:
    pop = meta.get("popularity") or {}
    # itemPopularity отдаёт числовые id предметов.
    phases = []
    for field, label in PHASES:
        counts = pop.get(field) or {}
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        items = []
        for item_id, count in ranked:
            key = consts.item_key_by_id.get(int(item_id))
            if not key:
                continue
            if field != "start_game_items" and not consts.is_key_item(key):
                continue
            items.append({**consts.item_ref(key), "count": count})
            if len(items) >= 6:
                break
        if items:
            phases.append({"phase": label, "items": items})
    return phases


def _components(key: str, consts: Constants) -> list[str]:
    return consts.items.get(key, {}).get("components") or []


def _owned_at(key: str, first: dict[str, int], consts: Constants) -> int | None:
    """Когда у игрока появился предмет или его замена: другие сапоги или апгрейд, собранный из него."""
    if key in first:
        return first[key]
    if key in BOOTS:
        times = [t for k, t in first.items() if k in BOOTS]
        if times:
            return min(times)
    upgrades = [t for k, t in first.items() if key in (consts.items.get(k, {}).get("components") or [])]
    return min(upgrades) if upgrades else None


def compare_build(player: dict, pos: int, duration: int, meta: dict | None, consts: Constants) -> dict:
    """Сравнить ключевые покупки игрока с про-матчами на том же герое (и по возможности позиции)."""
    first = first_purchases(player.get("purchase_log"))
    bought = sorted(((k, t) for k, t in first.items() if consts.is_key_item(k)), key=lambda kt: kt[1])
    # Промежуточный предмет, из которого потом собран другой ключевой (Yasha → Yasha and Kaya), в ленте не показываем.
    bought_keys = {k for k, _ in bought}
    bought = [(k, t) for k, t in bought
              if not any(k in _components(o, consts) for o in bought_keys if o != k)]

    result = {
        "available": False,
        "timeline": [{**consts.item_ref(k), "time": t, "time_fmt": fmt_time(t), "status": "unknown"} for k, t in bought],
        "core": [], "missing": [], "late": [], "offmeta": [],
        "score": None, "samples": 0, "basis": None, "popularity": [], "pro_examples": [],
    }
    if not meta:
        return result

    result["popularity"] = _popularity_view(meta, consts)
    n, basis, used, stats = _pro_item_stats(meta, pos, consts)
    result["samples"] = n
    result["basis"] = basis
    result["pro_examples"] = [
        {"match_id": s["match_id"], "name": s["name"], "league": s["league"], "pos": s["pos"], "win": s["win"]}
        for s in used[:5]
    ]
    if n < MIN_SAMPLES:
        return result
    result["available"] = True

    core = sorted(
        ((k, st) for k, st in stats.items() if st["share"] >= CORE_SHARE),
        key=lambda kv: kv[1]["median"],
    )
    pro_boots = {k for k, _ in core if k in BOOTS}
    result["core"] = []
    for k, st in core:
        owned = _owned_at(k, first, consts)
        result["core"].append({
            **consts.item_ref(k), "share": round(st["share"] * 100), "median": st["median"],
            "median_fmt": fmt_time(st["median"]), "p25_fmt": fmt_time(st["p25"]), "p75_fmt": fmt_time(st["p75"]),
            "bought_at": owned, "bought_fmt": fmt_time(owned) if owned is not None else None,
        })

    for entry in result["timeline"]:
        st = stats.get(entry["key"])
        t = entry["time"]
        if (not st or st["share"] < OFFMETA_SHARE) and entry["key"] in BOOTS and pro_boots:
            # Другие сапоги — не ошибка, просто подсказываем, что берут про.
            entry["status"] = "alt"
            entry["pro_alt"] = ", ".join(consts.item_name(b) for b in sorted(pro_boots))
            continue
        if not st or st["share"] < OFFMETA_SHARE:
            entry["status"] = "offmeta"
            result["offmeta"].append(entry)
            continue
        entry["pro_median"] = st["median"]
        entry["pro_median_fmt"] = fmt_time(st["median"])
        entry["pro_share"] = round(st["share"] * 100)
        entry["delta"] = t - st["median"]
        if st["share"] >= LATE_MIN_SHARE and t > st["p75"] + LATE_OVER_P75 and t - st["median"] > LATE_OVER_MEDIAN:
            entry["status"] = "late"
            result["late"].append(entry)
        elif t <= st["p25"]:
            entry["status"] = "early"
        else:
            entry["status"] = "on_time"

    core_keys = {k for k, _ in core}
    for k, st in core:
        if st["share"] < MISSING_SHARE or st["median"] + MISSING_MARGIN >= duration:
            continue
        if _owned_at(k, first, consts) is not None:
            continue
        # Не дублируем: если не собран и апгрейд (Force Staff → Hurricane Pike), говорим только про апгрейд.
        if any(k in _components(o, consts) for o in core_keys if o != k and _owned_at(o, first, consts) is None):
            continue
        result["missing"].append({**consts.item_ref(k), "share": round(st["share"] * 100),
                                  "median": st["median"], "median_fmt": fmt_time(st["median"])})

    # Оценка закупа 0..1: по коровым предметам, которые про успевают собрать до конца такого матча.
    # Компонент, чей апгрейд тоже в коре (Yasha при Manta), не считаем отдельно — судим по апгрейду.
    reachable = [(k, st) for k, st in core if st["median"] + 120 < duration]
    reachable_keys = {k for k, _ in reachable}
    reachable = [(k, st) for k, st in reachable
                 if not any(k in _components(o, consts) for o in reachable_keys if o != k)]
    if reachable:
        parts = []
        for k, st in reachable:
            t = _owned_at(k, first, consts)
            if t is None:
                # Начал собирать (есть компонент из ключевых) — частичный зачёт.
                started = any(c in first and consts.is_key_item(c) for c in _components(k, consts))
                parts.append(0.4 if started else 0.0)
            elif t <= st["p75"]:
                parts.append(1.0)
            else:
                parts.append(clamp(1 - (t - st["p75"]) / 900, 0.2, 1.0))
        result["score"] = sum(parts) / len(parts)
    return result
