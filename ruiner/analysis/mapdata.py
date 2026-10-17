"""Данные для карты матча: строения, варды, треки героев и точки смертей (координаты мира Dota)."""

from .core import fmt_time
from .replay_signals import Track

MAP_BOUNDS = (-8200, 8200)
TRACK_STEP = 2  # секунды между точками трека
TEAMS = {2: "radiant", 3: "dire"}


# Направления линий от своего Трона: у Света верх идёт на север, низ — на восток; у Тьмы наоборот.
LANE_DIRS = {
    "radiant": {"top": (0.0, 1.0), "mid": (0.707, 0.707), "bot": (1.0, 0.0)},
    "dire": {"top": (-1.0, 0.0), "mid": (-0.707, -0.707), "bot": (0.0, -1.0)},
}


def _assign_lanes(buildings: list[dict]) -> None:
    forts = {b["team"]: (b["x"], b["y"]) for b in buildings if b["kind"] == "fort"}
    for b in buildings:
        fort = forts.get(b["team"])
        dirs = LANE_DIRS.get(b["team"])
        if b["kind"] == "fort" or not fort or not dirs:
            b["lane"] = "base"
            continue
        dx, dy = b["x"] - fort[0], b["y"] - fort[1]
        norm = (dx * dx + dy * dy) ** 0.5 or 1
        b["lane"] = max(dirs, key=lambda lane: (dx * dirs[lane][0] + dy * dirs[lane][1]) / norm)


LABEL_LANES = {"верх": "top", "мид": "mid", "низ": "bot"}
LABEL_KINDS = {"башня": "tower", "барак": "barracks", "Трон": "fort"}


def _label_matches(label: str, b: dict) -> bool:
    """Подпись OpenDota («башня t2 · верх») совместима с типом и линией строения из реплея."""
    kind = next((k for prefix, k in LABEL_KINDS.items() if label.startswith(prefix)), None)
    if kind and kind != b["kind"]:
        return False
    lane = next((v for k, v in LABEL_LANES.items() if label.endswith(k)), None)
    return lane is None or lane == b["lane"]


def _building_times(buildings: list[dict], objectives: list[dict]) -> None:
    """Сущность строения удаляется через несколько секунд после сноса — берём точное время из OpenDota."""
    used = set()
    for b in sorted(buildings, key=lambda b: b["deleted"] or 1e9):
        if b["deleted"] is None:
            continue
        cands = [(i, o) for i, o in enumerate(objectives) if i not in used and o["kind"] == "building"
                 and o["team"] == b["team"] and _label_matches(o["label"], b)
                 and b["deleted"] - 40 <= o["time"] <= b["deleted"] + 2]
        if cands:
            i, o = min(cands, key=lambda io: abs(b["deleted"] - io[1]["time"]))
            used.add(i)
            b["destroyed"], b["label"] = o["time"], o["label"]
        else:
            b["destroyed"] = b["deleted"]


def build_map(parsed: dict, ctxs: list[dict], objectives: list[dict], match: dict, duration: int) -> dict:
    by_index = {}
    for c in ctxs:
        rp = c.get("rp")
        if rp:
            by_index[rp["index"]] = c

    buildings = []
    for b in parsed.get("buildings") or []:
        if b["kind"] == "watch_tower":
            continue
        buildings.append({"kind": b["kind"], "team": TEAMS.get(b["team"], "neutral"), "x": b["x"], "y": b["y"],
                          "deleted": b["deleted"], "destroyed": None, "label": None})
    _assign_lanes(buildings)
    _building_times(buildings, objectives)
    for b in buildings:
        if b["destroyed"] is not None and b["destroyed"] >= duration - 1 and b["kind"] != "fort":
            b["destroyed"] = None  # сущности удаляются в конце матча — это не снос
        b.pop("deleted")

    wards = []
    for w in parsed.get("wards") or []:
        owner = by_index.get(w["owner"])
        wards.append({"kind": w["kind"], "team": TEAMS.get(w["team"], "neutral"), "x": w["x"], "y": w["y"],
                      "start": w["created"], "end": w["deleted"] if w["deleted"] is not None else duration,
                      "slot": owner["slot"] if owner else None, "hero": owner["hero"] if owner else None})

    tracks, deaths = {}, []
    for c in ctxs:
        rp = c.get("rp")
        if not rp:
            continue
        pts, next_t = [], None
        for s in rp.get("samples") or []:
            t = s[0]
            if t is None or t < -90 or t > duration:
                continue
            if next_t is None or t >= next_t:
                pts.append([round(t), s[1], s[2], s[3]])
                next_t = t + TRACK_STEP
        tracks[c["slot"]] = pts
        track = Track(rp.get("samples") or [])
        for d in c["p"].get("deaths_log") or []:
            s = track.last_alive_before(d["time"])
            if not s:
                continue
            deaths.append({"slot": c["slot"], "hero": c["hero"], "team": c["team"], "time": int(d["time"]),
                           "time_fmt": fmt_time(d["time"]), "x": s[1], "y": s[2],
                           "killer": d.get("key")})

    deaths.sort(key=lambda d: d["time"])
    return {"bounds": MAP_BOUNDS, "duration": duration, "buildings": buildings, "wards": wards,
            "tracks": tracks, "deaths": deaths}
