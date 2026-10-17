"""Руинометр: вклад игрока 0–100 относительно нормы героя и позиции, и вердикт по нему."""

from statistics import median

from . import mode
from .core import CORE_POSITIONS, clamp, fmt_time, plural

# Ожидаемая доля нетворса команды по позициям.
EXPECTED_NW_SHARE = {1: 0.27, 2: 0.24, 3: 0.21, 4: 0.15, 5: 0.13}

CORE_WEIGHTS = {
    "gpm": 0.09, "xpm": 0.06, "lh": 0.07, "dmg": 0.12, "tower": 0.05,
    "kp": 0.14, "deaths": 0.14, "lane": 0.14, "nw": 0.09, "items": 0.10, "presence": 0.08, "counter": 0.05, "skills": 0.04,
}
SUPPORT_WEIGHTS = {
    "kp": 0.18, "deaths": 0.16, "dmg": 0.08, "xpm": 0.07, "lane": 0.12,
    "support": 0.22, "heal": 0.04, "gpm": 0.03, "items": 0.10, "presence": 0.08, "counter": 0.05, "skills": 0.04,
}

LABELS = {
    "gpm": "Золото в минуту", "xpm": "Опыт в минуту", "lh": "Добивания", "dmg": "Урон по героям",
    "tower": "Урон по строениям", "heal": "Лечение", "kp": "Участие в убийствах", "deaths": "Смерти",
    "lane": "Линия", "nw": "Доля нетворса", "support": "Работа саппорта", "items": "Закуп vs про",
    "presence": "Присутствие в игре", "counter": "Ответ на пик", "skills": "Прокачка vs про",
}

# Сколько секунд AFK (пока герой жив) обнуляют компонент присутствия.
AFK_ZERO_SECONDS = 300

VERDICTS = {"carried": "Тащил", "ok": "Норм", "questionable": "Под вопросом"}

# На сколько очков ниже медианы своей команды нужно быть, чтобы попасть «под вопрос».
QUESTION_GAP = 10


def _bench(ctx: dict, name: str):
    """Процентиль героя: в турбо — по своей турбо-выборке, иначе — benchmarks OpenDota."""
    source = ctx.get("bench") if ctx.get("bench") is not None else ctx["p"].get("benchmarks")
    b = (source or {}).get(name) or {}
    return b.get("raw"), b.get("pct")


def _ref(ctx: dict) -> str:
    return "турбо-игроков на этом герое" if ctx.get("bench") is not None else "игроков на этом герое"


def components(ctx: dict, duration: int) -> list[dict]:
    p = ctx["p"]
    pos = ctx["pos"]
    minutes = max(duration / 60, 1)
    out = []

    def add(key, value, text):
        if value is None:
            return
        out.append({"key": key, "label": LABELS[key], "value": round(clamp(value), 3), "text": text})

    for key, bench, unit in (("gpm", "gold_per_min", "GPM"), ("xpm", "xp_per_min", "XPM"),
                             ("lh", "last_hits_per_min", "добиваний в минуту"),
                             ("dmg", "hero_damage_per_min", "урона в минуту")):
        raw, pct = _bench(ctx, bench)
        if pct is not None:
            raw_s = f"{raw:.1f}" if isinstance(raw, float) and raw < 20 else f"{round(raw or 0)}"
            add(key, pct, f"{raw_s} {unit} — выше, чем у {round(pct * 100)}% {_ref(ctx)}")
    raw, pct = _bench(ctx, "tower_damage")
    if pct is not None:
        add("tower", pct, f"{round(raw or 0)} урона по строениям — {round(pct * 100)}-й процентиль героя")
    raw, pct = _bench(ctx, "hero_healing_per_min")
    if pct is not None and (p.get("hero_healing") or 0) > 0:
        add("heal", pct, f"{round(p.get('hero_healing') or 0)} лечения — {round(pct * 100)}-й процентиль героя")

    kp = ctx["kp"]
    add("kp", kp / 0.7, f"участие в {round(kp * 100)}% убийств команды")

    deaths = p.get("deaths") or 0
    per10 = deaths / minutes * 10
    dead_pct = ctx["dead_pct"]
    add("deaths", (clamp(1 - (per10 - 1) / 3) + clamp(1 - dead_pct / 0.35)) / 2,
        f"{deaths} смертей, мёртв {fmt_time(ctx['dead_s'])} ({round(dead_pct * 100)}% матча)")

    lane = ctx["lane"]
    if lane:
        opp_name = ctx["opp_hero"]
        if pos in CORE_POSITIONS:
            v = 0.5 + 0.25 * clamp(lane["lh_diff"] / 40, -1, 1) + 0.25 * clamp(lane["xp_diff"] / 2500, -1, 1)
        else:
            v = 0.5 + 0.4 * clamp(lane["xp_diff"] / 2000, -1, 1)
        v -= 0.08 * lane["deaths_unanswered"]
        unanswered = lane["deaths_unanswered"]
        add("lane", v, f"к {mode.P.lane_minute}:00 против {opp_name}: {lane['lh_diff']:+d} добиваний, {lane['xp_diff']:+d} опыта"
                       + (f", {plural(unanswered, 'смерть', 'смерти', 'смертей')} без размена" if unanswered else ""))

    if pos in CORE_POSITIONS:
        exp = EXPECTED_NW_SHARE[pos]
        share = ctx["nw_share"]
        add("nw", 0.5 + (share - exp) / (2 * exp),
            f"{round(share * 100)}% нетворса команды (норма для позиции ~{round(exp * 100)}%)")
    else:
        obs = p.get("obs_placed") or 0
        sen = p.get("sen_placed") or 0
        dewards = (p.get("observer_kills") or 0) + (p.get("sentry_kills") or 0)
        stacks = p.get("camps_stacked") or 0
        stuns = p.get("stuns") or 0
        vision = clamp((obs + sen * 0.5 + dewards + stacks * 0.5) / (minutes * 0.5))
        control = clamp(stuns / (minutes * 3))
        add("support", vision * 0.6 + control * 0.4,
            f"варды: {obs} обс. и {sen} сентри, снято {dewards}, стаков {stacks}, контроль {stuns:.0f} с")

    conduct = ctx.get("conduct") or {}
    if conduct.get("available"):
        afk = sum(w["seconds"] for w in conduct.get("afk") or [])
        add("presence", 1 - afk / AFK_ZERO_SECONDS,
            f"без приказов (пока жив) {fmt_time(afk)}" if afk else "AFK-отрезков от 90 с нет")

    personal = ctx.get("counters") or []
    if personal:
        done = [x for x in personal if x["have"]]
        add("counter", len(done) / len(personal),
            "; ".join(f"{x['label']}: {x['have']['name'] if x['have'] else 'нет ответа'}" for x in personal))

    sk = ctx.get("skills") or {}
    if sk.get("score") is not None:
        bits = []
        if sk.get("priority"):
            bits.append(f"первым {sk['priority']['name']}" + ("" if sk.get("priority_match") else
                        f" (про — {sk['pro_priority']['name']})"))
        if sk.get("ult_late"):
            bits.append("ульт не вовремя")
        add("skills", sk["score"], "; ".join(bits) or f"как у про ({sk['samples']} игр)")

    items = ctx.get("items") or {}
    if items.get("score") is not None:
        late = len(items.get("late") or [])
        missing = len(items.get("missing") or [])
        tail = []
        if late:
            tail.append(f"опозданий: {late}")
        if missing:
            tail.append(f"не собрано: {missing}")
        add("items", items["score"],
            f"ключевые предметы vs {items['samples']} {'турбо-игр' if items.get('turbo') else 'про-матчей'}" + (f" ({', '.join(tail)})" if tail else " — в тайминг"))
    return out


def score(ctx: dict, comps: list[dict]) -> int:
    weights = CORE_WEIGHTS if ctx["pos"] in CORE_POSITIONS else SUPPORT_WEIGHTS
    total = wsum = 0.0
    for c in comps:
        w = weights.get(c["key"], 0)
        c["weight"] = w
        total += w * c["value"]
        wsum += w
    return round(100 * total / wsum) if wsum else 50


def _confidence(margin: float) -> str:
    if margin >= 15:
        return "почти наверняка"
    if margin >= 8:
        return "вероятно"
    return "похоже"


def assign_verdicts(ctxs: list[dict]) -> None:
    """Вердикт относительно своей команды.

    В разгроме у всей проигравшей команды цифры низкие, поэтому «Под вопросом» — только тот, кто заметно
    ниже остальных своих и при этом либо слабый в абсолюте, либо собрал несколько спорных эпизодов.
    """
    for team in ("radiant", "dire"):
        members = [c for c in ctxs if c["team"] == team]
        top = max(c["score"] for c in members)
        for c in members:
            others = [o["score"] for o in members if o is not c]
            med = median(others) if others else 50
            c["team_median"] = med
            bad = c["bad_episodes"]
            s = c["score"]
            gap = med - s
            if s >= 68 and s == top and s - med >= 12:
                c["verdict"] = "carried"
                margin = min(s - 68, s - med - 12)
            elif s < 20 or (gap >= QUESTION_GAP and (s < 45 or bad >= 2)):
                c["verdict"] = "questionable"
                margin = max(20 - s, gap - QUESTION_GAP)
            else:
                c["verdict"] = "ok"
                margin = min(abs(gap - QUESTION_GAP), abs(68 - s))
            c["verdict_label"] = VERDICTS[c["verdict"]]
            c["confidence"] = _confidence(margin)
