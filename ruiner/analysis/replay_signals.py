"""Сигналы из своего разбора реплея: деньги при смерти, неиспользованные предметы, пропущенный байбек."""

from bisect import bisect_right

from ..constants import Constants
from . import mode
from .core import fmt_time, in_any_fight

# Предметы, которые спасают от смерти, если их прожать. Blink не берём: после урона он 3 с недоступен.
SAVE_ITEMS = {
    "black_king_bar", "glimmer_cape", "force_staff", "hurricane_pike", "ghost", "cyclone", "wind_waker",
    "lotus_orb", "manta", "invis_sword", "silver_edge", "satanic", "ethereal_blade", "crimson_guard",
    "pipe", "guardian_greaves", "disperser", "mekansm", "heavens_halberd", "harpoon",
}

# С какого запаса золота смерть считаем «с деньгами в кармане».
POCKET_GOLD = 2000
# С 20-й минуты оставляем на байбек.
BUYBACK_RESERVE_FROM = 20 * 60
BUYBACK_COOLDOWN = 480
# Байбек имел смысл, если до респауна оставалось не меньше этого.
BUYBACK_MIN_WAIT = 15


def buyback_cost(networth: int) -> int:
    """Оценка цены байбека по формуле клиента: 200 + нетворс / 13."""
    return int(200 + networth / 13)


class Track:
    """Выборки героя раз в секунду: [t, x, y, alive, gold, networth]."""

    def __init__(self, samples: list):
        self.s = [x for x in samples if x[0] is not None]
        self.t = [x[0] for x in self.s]

    def at(self, t: float):
        i = bisect_right(self.t, t) - 1
        return self.s[i] if i >= 0 else None

    def last_alive_before(self, t: float):
        i = bisect_right(self.t, t) - 1
        while i >= 0 and not self.s[i][3]:
            i -= 1
        return self.s[i] if i >= 0 else None

    def respawn_after(self, t: float) -> float | None:
        i = bisect_right(self.t, t)
        while i < len(self.s) and not self.s[i][3]:
            i += 1
        return self.s[i][0] if i < len(self.s) else None

    def dead_at(self, t: float) -> bool:
        s = self.at(t)
        return bool(s) and not s[3]


def _death_times(p: dict) -> list[int]:
    return sorted(int(d["time"]) for d in p.get("deaths_log") or [])


def pocket_gold(p: dict, track: Track) -> list[dict]:
    out = []
    for t in _death_times(p):
        s = track.last_alive_before(t)
        if not s:
            continue
        gold, nw = s[4], s[5]
        reserve = buyback_cost(nw) if t >= mode.P.buyback_reserve_from else 0
        if gold - reserve >= mode.P.pocket_gold:
            lost = next((d.get("gold_lost") for d in p.get("deaths_log") or [] if int(d["time"]) == t), None)
            out.append({"time": t, "gold": gold, "reserve": reserve, "lost": lost})
    return out


def _owned_items_at(p: dict, t: float, consts: Constants, uses_after: set[str]) -> set[str]:
    """Спасительные предметы, которые у игрока были на момент t (по логу покупок, с оглядкой на апгрейды)."""
    bought = {}
    for e in p.get("purchase_log") or []:
        bought.setdefault(e["key"], e["time"])
    final = {consts.item_key_by_id.get(p.get(f"{slot}")) for slot in
             ("item_0", "item_1", "item_2", "item_3", "item_4", "item_5", "backpack_0", "backpack_1", "backpack_2")}
    owned = set()
    for key, bt in bought.items():
        if key not in SAVE_ITEMS or bt > t - 5:
            continue
        upgraded = any(key in (consts.items.get(k, {}).get("components") or []) and kt <= t for k, kt in bought.items())
        if upgraded:
            continue
        if key in final or key in uses_after:
            owned.add(key)
    return owned


def unused_items(p: dict, hero_uses: list[tuple[float, str]], match: dict, consts: Constants) -> list[dict]:
    """Смерти в драке, когда спасительный предмет был, откатан и не прожат."""
    out = []
    for t in _death_times(p):
        if not in_any_fight(match, t):
            continue
        used_after = {k for ut, k in hero_uses if ut > t}
        unused = []
        for key in _owned_items_at(p, t, consts, used_after):
            cd = consts.items.get(key, {}).get("cd") or 30
            window = max(float(cd), 20.0)
            if not any(k == key and t - window <= ut <= t for ut, k in hero_uses):
                unused.append(key)
        if unused:
            out.append({"time": t, "items": [consts.item_ref(k) for k in sorted(unused)]})
    return out


def missed_buybacks(p: dict, track: Track, team_losses: list[dict]) -> list[dict]:
    """База падала, игрок был мёртв долго, деньги на байбек были, а байбек не нажат."""
    base = [o for o in team_losses if o["label"].startswith(("барак", "башня t3", "башня t4"))]
    buybacks = sorted(int(b["time"]) for b in p.get("buyback_log") or [])
    out, last = [], -10**9
    for o in base:
        t = o["time"]
        if t - last < 60 or not track.dead_at(t):
            continue
        respawn = track.respawn_after(t)
        if respawn is None or respawn - t < BUYBACK_MIN_WAIT:
            continue
        if any(t - BUYBACK_COOLDOWN <= b <= respawn for b in buybacks):
            continue
        s = track.at(t)
        cost = buyback_cost(s[5])
        if s[4] >= cost:
            out.append({"time": t, "label": o["label"], "wait": round(respawn - t), "gold": s[4], "cost": cost})
            last = t
    return out


def player_signals(ctx: dict, match: dict, parsed: dict, consts: Constants) -> dict:
    rp = ctx.get("rp")
    if not rp:
        return {"available": False}
    p = ctx["p"]
    npc = consts.heroes.get(p["hero_id"], {}).get("name")
    uses = sorted((u[0], u[2].removeprefix("item_")) for u in parsed.get("item_uses") or []
                  if u[1] == npc and u[0] is not None)
    track = Track(rp.get("samples") or [])
    return {
        "available": True,
        "pocket": pocket_gold(p, track),
        "unused": unused_items(p, uses, match, consts),
        "buyback": missed_buybacks(p, track, ctx["team_losses"]),
        "item_uses": len(uses),
    }


def signal_episodes(ctx: dict, make_episode) -> list[dict]:
    sig = ctx.get("signals") or {}
    if not sig.get("available"):
        return []
    hero = ctx["hero"]
    out = []
    for d in sig["pocket"][:3]:
        lost = f", потеряно {d['lost']}" if d.get("lost") else ""
        reserve = f" (сверх {d['reserve']} на байбек)" if d["reserve"] else ""
        out.append(make_episode(ctx, d["time"], "Деньги в кармане", "Смерть с крупной суммой непотраченного золота",
                                f"{hero} — умер на {fmt_time(d['time'])} с {d['gold']} золота{reserve}{lost}",
                                "disputed"))
    for d in sig["unused"][:3]:
        names = ", ".join(i["name"] for i in d["items"])
        out.append(make_episode(ctx, d["time"], "Умер с откатанным предметом",
                                "Смерть в драке: спасительный предмет был готов, но не использован",
                                f"{hero} — умер в драке на {fmt_time(d['time'])}, не прожав {names}", "disputed"))
    for d in sig["buyback"]:
        out.append(make_episode(ctx, d["time"], "Не выкупился",
                                "Падала база, до респауна далеко, золота на байбек хватало",
                                f"{hero} — {d['label']} упал(а) на {fmt_time(d['time'])}, до респауна {d['wait']} с, "
                                f"золота {d['gold']} при цене байбека ~{d['cost']}", "disputed"))
    return out
