"""Прокачка способностей против про-матчей на том же герое: что максил первым, ульт вовремя, таланты."""

from collections import Counter
from statistics import median

from ..constants import Constants
from .items import MIN_POS_SAMPLES, MIN_SAMPLES

# Сколько первых очков навыков смотрим, чтобы понять, что игрок максил первым.
PRIORITY_POINTS = 9
TALENT_LEVELS = {1: 10, 2: 15, 3: 20, 4: 25}
SKIP_PREFIXES = ("special_bonus", "attribute_bonus", "generic_hidden", "plus_")


def _keys(ids: list, consts: Constants) -> list[str]:
    return [k for k in (consts.ability_key(i) for i in ids or []) if k]


def _is_talent(k: str) -> bool:
    return k.startswith("special_bonus")


def _ultimates(builds: list[list[str]], consts: Constants) -> set[str]:
    """Ульт по справочнику (3 уровня), а если не определился — способность, которую никто не берёт раньше 6 уровня."""
    ults = {k for b in builds for k in b if not k.startswith(SKIP_PREFIXES) and consts.is_ultimate(k)}
    if ults:
        return ults
    first_level = {}
    for b in builds:
        for lvl, k in enumerate(b, 1):
            if not k.startswith(SKIP_PREFIXES):
                first_level[k] = min(first_level.get(k, 99), lvl)
    late = {k for k, lvl in first_level.items() if lvl >= 6}
    return late if len(late) == 1 else set()


def _priority(build: list[str], ults: set[str]) -> str | None:
    """Навык, в который ушло больше всего очков за первые уровни (при равенстве — тот, что качали раньше)."""
    points = Counter()
    first_seen = {}
    for i, k in enumerate(build[:PRIORITY_POINTS]):
        if k.startswith(SKIP_PREFIXES) or k in ults:
            continue
        points[k] += 1
        first_seen.setdefault(k, i)
    if not points:
        return None
    return max(points, key=lambda k: (points[k], -first_seen[k]))


def _talents(build: list[str], tiers: dict[str, int]) -> dict[int, str]:
    return {tiers[k]: k for k in build if _is_talent(k) and k in tiers}


def _ult_points(build: list[str], ults: set[str]) -> list[int]:
    return [i for i, k in enumerate(build, 1) if k in ults]


def _ult_late(build: list[str], pro_builds: list[list[str]], ults: set[str]) -> list[dict]:
    """Уровень ульта взят заметно позже, чем у про (по номеру очка прокачки, а не уровню героя:
    таланты и уровни без очков сдвигают нумерацию)."""
    mine = _ult_points(build, ults)
    pro = [_ult_points(b, ults) for b in pro_builds]
    out = []
    for n in range(3):
        idx = [pts[n] for pts in pro if len(pts) > n]
        if len(idx) < MIN_SAMPLES:
            break
        typical = round(median(idx))
        if len(build) < typical + 2:
            break
        got = mine[n] if n < len(mine) else None
        if got is None or got > typical + 1:
            out.append({"rank": n + 1, "typical": typical, "taken": got})
    return out


def compare_skills(player: dict, pos: int, meta: dict | None, consts: Constants) -> dict:
    hero_id = player["hero_id"]
    build = _keys(player.get("ability_upgrades_arr"), consts)
    tiers = consts.hero_talents(hero_id)
    result = {"available": False, "samples": 0, "basis": None,
              "build": [{**consts.ability_ref(k), "level": i} for i, k in enumerate(build, 1)]}
    if not build or not meta:
        return result

    samples = [s for s in meta.get("samples") or [] if s.get("skills")]
    same_pos = [s for s in samples if s.get("pos") == pos]
    use = same_pos if len(same_pos) >= MIN_POS_SAMPLES else samples
    result["samples"], result["basis"] = len(use), "pos" if use is same_pos else "all"
    if len(use) < MIN_SAMPLES:
        return result
    pro_builds = [_keys(s["skills"], consts) for s in use]
    ults = _ultimates(pro_builds + [build], consts)

    pro_prio = Counter(p for p in (_priority(b, ults) for b in pro_builds) if p)
    mine = _priority(build, ults)
    top, top_n = pro_prio.most_common(1)[0] if pro_prio else (None, 0)

    talents_mine = _talents(build, tiers)
    talent_rows = []
    for tier in sorted(TALENT_LEVELS):
        picks = Counter(t for t in (_talents(b, tiers).get(tier) for b in pro_builds) if t)
        if not picks:
            continue
        pro_key, n = picks.most_common(1)[0]
        mine_key = talents_mine.get(tier)
        talent_rows.append({
            "tier": tier, "level": TALENT_LEVELS[tier],
            "mine": consts.ability_ref(mine_key) if mine_key else None,
            "pro": consts.ability_ref(pro_key), "pro_share": round(n / sum(picks.values()) * 100),
            "match": mine_key == pro_key if mine_key else None,
        })

    # У героев с несколькими ультами (Kez) порядок слишком разный — не сравниваем.
    ult_late = _ult_late(build, pro_builds, ults) if len(ults) == 1 else []
    result.update({
        "available": True,
        "ultimates": sorted(ults),
        "priority": consts.ability_ref(mine) if mine else None,
        "pro_priority": consts.ability_ref(top) if top else None,
        "pro_priority_share": round(top_n / len(pro_builds) * 100) if top else None,
        "priority_match": (mine == top) if mine and top else None,
        "talents": talent_rows,
        "ult_late": ult_late,
    })
    parts = []
    if result["priority_match"] is not None:
        parts.append((0.5, 1.0 if result["priority_match"] else 0.0))
    decided = [r for r in talent_rows if r["match"] is not None]
    if decided:
        parts.append((0.3, sum(1 for r in decided if r["match"]) / len(decided)))
    if ults:
        parts.append((0.2, 0.0 if ult_late else 1.0))
    if parts:
        result["score"] = sum(w * v for w, v in parts) / sum(w for w, _ in parts)
    return result


def skill_episodes(ctx: dict, make_episode) -> list[dict]:
    """Эпизоды прокачки «мелкие»: влияют на оценку через компонент, но не делают вердикт сами по себе."""
    episodes = _skill_episodes(ctx, make_episode)
    for e in episodes:
        e["minor"] = True
    return episodes


def _skill_episodes(ctx: dict, make_episode) -> list[dict]:
    sk = ctx.get("skills") or {}
    if not sk.get("available"):
        return []
    hero = ctx["hero"]
    basis = "на этой позиции" if sk["basis"] == "pos" else "на герое"
    who = sk.get("ref", "про")
    out = []
    if sk.get("priority_match") is False and (sk.get("pro_priority_share") or 0) >= 60:
        out.append(make_episode(ctx, 60 * 4, f"Прокачка не как у {who}", f"Какой навык {who} максят первым",
                                f"{hero} — первым качал {sk['priority']['name']}, {who} {basis} — "
                                f"{sk['pro_priority']['name']} ({sk['pro_priority_share']}% из {sk['samples']} игр)",
                                "disputed"))
    for u in sk.get("ult_late") or []:
        taken = f"взят {u['taken']}-м очком" if u["taken"] else "не взят"
        out.append(make_episode(ctx, 60 * (u["typical"] + 1), "Ульт не вовремя",
                                f"{who.capitalize()} берут этот уровень ульта сразу, как он доступен",
                                f"{hero} — {u['rank']}-й уровень ульта у {who} обычно {u['typical']}-м очком прокачки, "
                                f"а здесь {taken}", "disputed"))
    differ = [r for r in sk.get("talents") or [] if r["match"] is False and r["pro_share"] >= 70]
    if differ:
        text = "; ".join(f"{r['level']}: взял «{r['mine']['name']}», {who} — «{r['pro']['name']}» ({r['pro_share']}%)"
                         for r in differ)
        out.append(make_episode(ctx, 60 * 12, f"Таланты не как у {who}", f"Какой талант {who} берут на этом ярусе",
                                f"{hero} — {text}", "fact"))
    return out
