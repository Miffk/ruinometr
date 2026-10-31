"""Позиционный разбор по трекам из реплея: с кем и где умирал, стоял ли рядом с дракой, сколько жили варды."""

from . import mode
from .core import fights_after, fmt_time, in_any_fight, plural, took_part
from .replay_signals import Track

# Союзник ближе этого (в единицах карты) — умер не один: мог помочь или размениваться.
ALLY_NEAR = 1600
# Враги ближе этого в момент смерти — те, кто участвовал в убийстве.
ENEMY_NEAR = 1800
# Радиус обзора обсервера (как на карте матча).
OBS_VISION = 1600
OBS_LIFETIME = 360
# Вард снят быстро, если прожил меньше этого.
WARD_QUICK = 90
# Ближе этого к своей базе, чем к вражеской, — уже чужая половина карты.
ENEMY_SIDE_MARGIN = 2000
# Жив и ближе этого к центру драки на её начале — мог прийти.
FIGHT_NEAR = 3000
# Выборка трека считается актуальной, если отстаёт не больше чем на столько секунд.
SAMPLE_SLACK = 3

TEAM_NUM = {"radiant": 2, "dire": 3}


def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _pos(track: Track, t: float, alive_only: bool = True):
    """(x, y) героя в момент t, если выборка свежая (и герой жив)."""
    s = track.at(t)
    if not s or t - s[0] > SAMPLE_SLACK or s[1] is None or s[2] is None:
        return None
    if alive_only and not s[3]:
        return None
    return s[1], s[2]


def _forts(parsed: dict) -> dict[str, tuple[float, float]]:
    out = {}
    for b in parsed.get("buildings") or []:
        if b["kind"] == "fort":
            team = next((k for k, v in TEAM_NUM.items() if v == b["team"]), None)
            if team:
                out[team] = (b["x"], b["y"])
    return out


def _enemy_side(team: str, xy, forts: dict) -> bool:
    enemy = "dire" if team == "radiant" else "radiant"
    if team in forts and enemy in forts:
        return _dist(xy, forts[enemy]) < _dist(xy, forts[team]) - ENEMY_SIDE_MARGIN
    # Без Тронов в реплее: река примерно по диагонали x + y = 0, Свет — снизу слева.
    s = xy[0] + xy[1]
    return s > ENEMY_SIDE_MARGIN if team == "radiant" else s < -ENEMY_SIDE_MARGIN


def _team_obs(parsed: dict, team: str) -> list[dict]:
    num = TEAM_NUM[team]
    return [w for w in parsed.get("wards") or [] if w["kind"] == "observer" and w["team"] == num
            and w["created"] is not None]


def _covered(obs: list[dict], xy, t: float) -> bool:
    for w in obs:
        end = w["deleted"] if w["deleted"] is not None else 1e9
        if w["created"] <= t < end and _dist(xy, (w["x"], w["y"])) <= OBS_VISION:
            return True
    return False


def _deaths(ctx, tracks, ctxs, match, parsed, forts) -> list[dict]:
    track = tracks[ctx["slot"]]
    obs = _team_obs(parsed, ctx["team"])
    out = []
    for d in ctx["p"].get("deaths_log") or []:
        t = int(d["time"])
        s = track.last_alive_before(t)
        if not s or t - s[0] > 10:
            continue
        xy, ts = (s[1], s[2]), s[0]
        allies = enemies = 0
        for o in ctxs:
            if o is ctx or o["slot"] not in tracks:
                continue
            oxy = _pos(tracks[o["slot"]], ts)
            if oxy is None:
                continue
            if o["team"] == ctx["team"]:
                allies += _dist(xy, oxy) <= ALLY_NEAR
            else:
                enemies += _dist(xy, oxy) <= ENEMY_NEAR
        fight = in_any_fight(match, t)
        out.append({
            "time": t, "x": xy[0], "y": xy[1], "allies_near": allies, "enemies_near": enemies,
            "alone": allies == 0 and not fight, "vision": _covered(obs, xy, t),
            "enemy_side": _enemy_side(ctx["team"], xy, forts), "fight": fight,
        })
    return out


def _fights(ctx, tracks, ctxs, match) -> dict:
    """Драки после линии, где игрок не участвовал: был мёртв, далеко или рядом."""
    track = tracks[ctx["slot"]]
    dead = far = 0
    near = []
    for f in fights_after(match, mode.P.lane_end):
        if took_part(f, ctx["idx"]):
            continue
        start = f["start"]
        me = _pos(track, start)
        if me is None:
            dead += 1
            continue
        pts = [_pos(tracks[o["slot"]], start) for o in ctxs
               if o["slot"] in tracks and took_part(f, o["idx"])]
        pts = [p for p in pts if p is not None]
        if not pts:
            continue
        center = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        dist = _dist(me, center)
        if dist <= FIGHT_NEAR:
            near.append({"time": start, "end": f["end"], "dist": round(dist)})
        else:
            far += 1
    return {"dead": dead, "far": far, "near": near}


def _wards(ctx, parsed: dict, duration: int) -> dict | None:
    rp = ctx["rp"]
    mine = [w for w in parsed.get("wards") or [] if w["kind"] == "observer" and w["owner"] == rp["index"]
            and w["created"] is not None and w["created"] < duration - 30]
    if not mine:
        return None
    fracs, quick = [], []
    for w in mine:
        end = w["deleted"] if w["deleted"] is not None else duration
        life = end - w["created"]
        if end < duration - 5 and life < WARD_QUICK:
            quick.append(w["created"])
        # Вард, который не успел истечь до конца матча, считаем по доступному ему времени.
        possible = min(OBS_LIFETIME, duration - w["created"])
        fracs.append(min(life / possible, 1.0) if possible > 0 else 1.0)
    return {"placed": len(mine), "quick": len(quick), "first_quick": min(quick) if quick else None,
            "survival": round(sum(fracs) / len(fracs), 2)}


def analyze(ctxs: list[dict], match: dict, parsed: dict | None, duration: int) -> None:
    """Заполняет ctx["positioning"] у каждого игрока, для которого есть трек из реплея."""
    tracks = {c["slot"]: Track(c["rp"].get("samples") or []) for c in ctxs if c.get("rp")}
    forts = _forts(parsed) if parsed else {}
    for c in ctxs:
        if not parsed or c["slot"] not in tracks:
            c["positioning"] = {"available": False}
            continue
        deaths = _deaths(c, tracks, ctxs, match, parsed, forts)
        late = [d for d in deaths if d["time"] >= mode.P.lane_end]
        alone = [d for d in late if d["alone"]]
        c["positioning"] = {
            "available": True,
            "deaths": deaths,
            "alone": len(alone),
            "risky": sum(1 for d in alone if d["enemy_side"] and not d["vision"]),
            "in_fight": sum(1 for d in late if not d["alone"]),
            "fights": _fights(c, tracks, ctxs, match),
            "wards": _wards(c, parsed, duration),
        }


def score_value(pos: dict, duration: int) -> float:
    """1 — без смертей в одиночку и пропущенных драк рядом; штрафы приведены к ~25 минутам после линии."""
    span = max(duration - mode.P.lane_end, 60)
    k = min(1.0, 25 * 60 / span)
    penalty = 0.12 * pos["alone"] + 0.08 * pos["risky"] + 0.12 * len(pos["fights"]["near"])
    return max(0.0, 1 - penalty * k)


def score_text(pos: dict) -> str:
    bits = [f"смертей в одиночку после {mode.P.lane_minute}:00: {pos['alone']}"]
    if pos["risky"]:
        bits[0] += f" (на чужой половине без варда: {pos['risky']})"
    near = len(pos["fights"]["near"])
    bits.append(f"пропущено драк рядом: {near}" if near else "драк рядом не пропускал")
    return "; ".join(bits)


def _times(items, key="time", limit=5) -> str:
    s = ", ".join(fmt_time(x[key]) for x in items[:limit])
    return s + ("…" if len(items) > limit else "")


def episodes(ctx, make_episode) -> list[dict]:
    pos = ctx.get("positioning") or {}
    if not pos.get("available"):
        return []
    hero = ctx["hero"]
    support = ctx["pos"] not in (1, 2, 3)
    out = []

    late = [d for d in pos["deaths"] if d["time"] >= mode.P.lane_end]
    alone = [d for d in late if d["alone"]]
    risky = [d for d in alone if d["enemy_side"] and not d["vision"]]
    # Саппорт чаще ходит один (варды, разведка) — порог выше.
    if len(alone) >= (4 if support else 3) or len(risky) >= (3 if support else 2):
        text = (f"{hero} — {plural(len(alone), 'смерть', 'смерти', 'смертей')} после {mode.P.lane_minute}:00 без союзников "
                f"ближе {ALLY_NEAR} и вне драк ({_times(alone)})")
        if risky:
            text += f"; из них {len(risky)} — на чужой половине карты без нашего обсервера рядом"
        out.append(make_episode(ctx, alone[0]["time"], "Пойман в соло",
                                "Смерть без союзников рядом (по позициям из реплея), вне командных драк",
                                text, "disputed", end=alone[-1]["time"]))

    near = pos["fights"]["near"]
    if len(near) >= 2:
        out.append(make_episode(ctx, near[0]["time"], "Стоял рядом с дракой",
                                f"Жив и ближе {FIGHT_NEAR} к драке на её начале, но в ней не участвовал",
                                f"{hero} — {plural(len(near), 'драка', 'драки', 'драк')} без участия, хотя был рядом: "
                                + ", ".join(f"{fmt_time(n['time'])} ({n['dist']})" for n in near[:5]),
                                "disputed", end=near[-1]["end"]))

    w = pos.get("wards")
    if w and w["placed"] >= 4 and w["quick"] / w["placed"] >= 0.5:
        e = make_episode(ctx, w["first_quick"], "Варды снимали сразу",
                         f"Половина обсерверов и больше снята врагом быстрее {WARD_QUICK} с",
                         f"{hero} — из {w['placed']} обсерверов {w['quick']} сняли быстрее {WARD_QUICK} с; "
                         f"в среднем вард прожил {round(w['survival'] * 100)}% срока", "disputed")
        e["minor"] = True  # тут многое решает враг: в вердикт не идёт
        out.append(e)
    return out
