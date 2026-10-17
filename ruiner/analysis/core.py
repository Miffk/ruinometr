"""Базовые вычисления по разобранному матчу: позиции, линия, драки, смерти."""

from statistics import median

from . import mode

# Против кого стоит позиция на линии: керри против хардлейнера, мид против мида, саппорты друг против друга.
LANE_OPPONENT_POS = {1: 3, 2: 2, 3: 1, 4: 5, 5: 4}
POS_LABELS = {1: "поз. 1 · лёгкая", 2: "поз. 2 · центр", 3: "поз. 3 · сложная", 4: "поз. 4 · сложная", 5: "поз. 5 · лёгкая"}
CORE_POSITIONS = {1, 2, 3}


def fmt_time(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    s = int(round(seconds))
    sign = "-" if s < 0 else ""
    s = abs(s)
    return f"{sign}{s // 60}:{s % 60:02d}"


def stage_of(t: float, duration: int) -> str:
    lane_end, final = mode.P.lane_end, mode.P.final_window
    if t < lane_end:
        return "lane"
    if duration > lane_end + final and t >= duration - final:
        return "final"
    return "mid"


def plural(n: int, one: str, few: str, many: str) -> str:
    """plural(3, 'смерть', 'смерти', 'смертей') → '3 смерти'."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        word = one
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        word = few
    else:
        word = many
    return f"{n} {word}"


def at_minute(arr: list | None, minute: int):
    if not arr:
        return None
    return arr[min(minute, len(arr) - 1)]


def assign_positions(players: list[dict]) -> dict[int, int]:
    """Позиция 1–5 для каждого player_slot. Берём оценку OpenDota, при конфликте — по линии и нетворсу."""
    result: dict[int, int] = {}
    for is_radiant in (True, False):
        team = [p for p in players if bool(p.get("isRadiant")) == is_radiant]
        est = [p.get("position_est") for p in team]
        if all(isinstance(e, int) and 1 <= e <= 5 for e in est) and len(set(est)) == len(team):
            for p in team:
                result[p["player_slot"]] = p["position_est"]
            continue
        # Запасной вариант: на каждой линии богатший — кор, остальные — саппорты.
        by_nw = sorted(team, key=lambda p: p.get("net_worth") or 0, reverse=True)
        free = [1, 2, 3, 4, 5]
        wanted = {1: (1, 5), 2: (2, 4), 3: (3, 4)}
        taken_lane = set()
        for p in by_nw:
            role = p.get("lane_role")
            options = wanted.get(role, ())
            pos = None
            if role in wanted and role not in taken_lane and options[0] in free:
                pos = options[0]
                taken_lane.add(role)
            else:
                for o in options[1:]:
                    if o in free:
                        pos = o
                        break
            if pos is None:
                continue
            free.remove(pos)
            result[p["player_slot"]] = pos
        for p in by_nw:
            if p["player_slot"] not in result:
                result[p["player_slot"]] = free.pop(0)
    return result


def team_of(p: dict) -> str:
    return "radiant" if p.get("isRadiant") else "dire"


def death_times(p: dict) -> list[int]:
    return sorted(int(d["time"]) for d in p.get("deaths_log") or [])


def kill_times(p: dict) -> list[int]:
    return sorted(int(k["time"]) for k in p.get("kills_log") or [])


def fights_after(match: dict, start: int) -> list[dict]:
    return [f for f in match.get("teamfights") or [] if f.get("start", 0) >= start]


def took_part(fight: dict, idx: int) -> bool:
    players = fight.get("players") or []
    if idx >= len(players):
        return False
    e = players[idx]
    return bool(
        e.get("deaths") or e.get("damage") or e.get("healing") or e.get("killed")
        or e.get("ability_uses") or e.get("item_uses") or e.get("buybacks")
    )


def in_any_fight(match: dict, t: int, slack: int = 5) -> bool:
    for f in match.get("teamfights") or []:
        if f.get("start", 0) - slack <= t <= f.get("end", 0) + slack:
            return True
    return False


def lane_result(p: dict, opp: dict | None, minute: int | None = None) -> dict | None:
    if opp is None:
        return None
    minute = minute or mode.P.lane_minute
    lh, olh = at_minute(p.get("lh_t"), minute), at_minute(opp.get("lh_t"), minute)
    dn, odn = at_minute(p.get("dn_t"), minute), at_minute(opp.get("dn_t"), minute)
    xp, oxp = at_minute(p.get("xp_t"), minute), at_minute(opp.get("xp_t"), minute)
    gold, ogold = at_minute(p.get("gold_t"), minute), at_minute(opp.get("gold_t"), minute)
    if None in (lh, olh, xp, oxp):
        return None
    lane_end = minute * 60
    deaths = sum(1 for t in death_times(p) if t < lane_end)
    kills = sum(1 for t in kill_times(p) if t < lane_end)
    return {
        "lh": lh, "opp_lh": olh, "lh_diff": lh - olh,
        "dn": dn, "opp_dn": odn,
        "xp": xp, "opp_xp": oxp, "xp_diff": xp - oxp,
        "gold_diff": (gold - ogold) if gold is not None and ogold is not None else None,
        "deaths": deaths, "kills": kills,
        "deaths_unanswered": max(0, deaths - kills),
    }


def quantile(values: list[float], q: float) -> float:
    vs = sorted(values)
    if not vs:
        raise ValueError("empty")
    if len(vs) == 1:
        return vs[0]
    pos = (len(vs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(vs) - 1)
    return vs[lo] + (vs[hi] - vs[lo]) * (pos - lo)


def safe_median(values):
    return median(values) if values else None


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
