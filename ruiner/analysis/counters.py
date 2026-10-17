"""Закуп с учётом вражеского пика: есть ли ответ на уклонение, пассивки, лечение, невидимость, контроль, иллюзии.

Таблицы ниже — эвристики, не истина: они говорят «против этого обычно покупают это», а вердикт помечается «Спорно».
"""

from ..constants import Constants
from . import mode
from .core import CORE_POSITIONS, fmt_time

# Сколько вражеских героев с сильным контролем — «много контроля», нужен BKB или Linken's.
DISABLERS_FOR_BKB = 3
# Роль Disabler у OpenDota слишком широкая (она есть у большинства героев), поэтому свой список:
# герои, чей контроль решает драки и от которого спасает BKB.
HEAVY_CONTROL = {
    "lion", "shadow_shaman", "earthshaker", "crystal_maiden", "sven", "magnataur", "enigma", "faceless_void",
    "tidehunter", "bane", "mars", "centaur", "disruptor", "silencer", "skywrath_mage", "doom_bringer", "beastmaster",
    "batrider", "legion_commander", "pudge", "axe", "slardar", "sand_king", "spirit_breaker", "kunkka", "ogre_magi",
    "dark_seer", "puck", "invoker", "winter_wyvern", "warlock", "tiny", "nyx_assassin", "elder_titan", "treant",
    "chaos_knight", "primal_beast", "snapfire", "void_spirit", "lina", "shadow_demon", "vengefulspirit", "rubick",
    "grimstroke", "jakiro", "dawnbreaker", "storm_spirit", "bloodseeker", "riki", "night_stalker", "largo",
}
# С какой длины матча ждём ответ на пик (раньше ключевые предметы просто не успеть).
MIN_DURATION = {"evasion": 20 * 60, "control": 22 * 60, "break": 20 * 60, "heal": 18 * 60,
                "illusions": 20 * 60, "invis": 10 * 60}

THREATS = {
    "evasion": {
        "label": "уклонение",
        "heroes": {"phantom_assassin", "windrunner", "brewmaster"},
        "enemy_items": {"butterfly", "heavens_halberd"},
        "counters": ["monkey_king_bar", "bloodthorn"],
        "scope": "player",
        "who": "right_click",
    },
    "control": {
        "label": "много контроля",
        "heroes": set(),
        "enemy_items": set(),
        "counters": ["black_king_bar", "sphere"],
        "scope": "player",
        "who": "carry_mid",
    },
    "break": {
        "label": "пассивки (нужен Break)",
        "heroes": {"bristleback", "phantom_assassin", "spectre", "huskar", "viper", "shredder", "tidehunter", "ursa",
                   "slardar", "dragon_knight", "life_stealer", "skeleton_king", "slark", "faceless_void", "antimage",
                   "troll_warlord"},
        "enemy_items": set(),
        "counters": ["silver_edge"],
        "scope": "cores",
    },
    "illusions": {
        "label": "иллюзии и призывы",
        "heroes": {"phantom_lancer", "naga_siren", "chaos_knight", "terrorblade", "meepo", "broodmother", "lycan",
                   "furion", "enigma", "lone_druid"},
        "enemy_items": set(),
        "counters": ["mjollnir", "maelstrom", "gungir", "bfury", "radiance", "shivas_guard"],
        "scope": "cores",
    },
    "heal": {
        "label": "лечение и реген",
        "heroes": {"necrolyte", "alchemist", "huskar", "undying", "abaddon", "oracle", "dazzle", "omniknight",
                   "witch_doctor", "chen", "treant", "warlock", "wisp", "morphling", "life_stealer", "dragon_knight",
                   "enchantress", "dawnbreaker", "skeleton_king", "juggernaut"},
        "enemy_items": {"satanic", "holy_locket", "heart", "guardian_greaves"},
        "counters": ["spirit_vessel", "shivas_guard", "skadi"],
        "scope": "team",
    },
    "invis": {
        "label": "невидимость",
        "heroes": {"riki", "clinkz", "bounty_hunter", "weaver", "nyx_assassin", "mirana", "invoker", "treant"},
        "enemy_items": {"invis_sword", "silver_edge", "shadow_amulet"},
        "counters": ["ward_sentry", "dust", "gem"],
        "scope": "detection",
    },
}


def _npc(consts: Constants, hero_id: int) -> str:
    return consts.heroes.get(hero_id, {}).get("name", "").replace("npc_dota_hero_", "")


def _owned(p: dict, keys: list[str], consts: Constants) -> tuple[str, int] | None:
    """Первый купленный ответ из списка — сам предмет или апгрейд, в который он входит."""
    best = None
    for e in p.get("purchase_log") or []:
        k = e["key"]
        hit = k in keys or any(c in keys for c in consts.items.get(k, {}).get("components") or [])
        if hit and (best is None or e["time"] < best[1]):
            best = (k, e["time"])
    return best


def _enemy_triggers(threat: dict, enemies: list[dict], consts: Constants) -> list[str]:
    names = []
    for c in enemies:
        p = c["p"]
        why = None
        if _npc(consts, p["hero_id"]) in threat["heroes"]:
            why = c["hero"]
        else:
            bought = {e["key"] for e in p.get("purchase_log") or []}
            item = next((k for k in threat["enemy_items"] if k in bought), None)
            if item:
                why = f"{c['hero']} ({consts.item_name(item)})"
        if why:
            names.append(why)
    return names


def _is_right_click(c: dict, consts: Constants) -> bool:
    """Керри всегда; мид и хард — только ловкостные керри, которые и правда бьют рукой."""
    hero = consts.heroes.get(c["p"]["hero_id"], {})
    return c["pos"] == 1 or (c["pos"] in CORE_POSITIONS and "Carry" in (hero.get("roles") or [])
                             and hero.get("primary_attr") == "agi")


def analyze(ctxs: list[dict], consts: Constants, duration: int) -> list[dict]:
    """Ставит ctx["counters"] каждому игроку и возвращает командные выводы (антихил, детект, Break, AoE)."""
    team_findings = []
    for c in ctxs:
        c["counters"] = []
    for team in ("radiant", "dire"):
        mates = [c for c in ctxs if c["team"] == team]
        enemies = [c for c in ctxs if c["team"] != team]
        disablers = [e["hero"] for e in enemies if _npc(consts, e["p"]["hero_id"]) in HEAVY_CONTROL]
        for key, threat in THREATS.items():
            if duration < mode.P.t(MIN_DURATION[key]):
                continue
            triggers = disablers if key == "control" and len(disablers) >= DISABLERS_FOR_BKB else \
                ([] if key == "control" else _enemy_triggers(threat, enemies, consts))
            if not triggers:
                continue
            wanted = [consts.item_ref(k) for k in threat["counters"] if k in consts.items]
            base = {"threat": key, "label": threat["label"], "enemies": triggers, "wanted": wanted}
            scope = threat["scope"]
            if scope == "player":
                for c in mates:
                    applies = _is_right_click(c, consts) if threat["who"] == "right_click" else c["pos"] in (1, 2)
                    if not applies:
                        continue
                    have = _owned(c["p"], threat["counters"], consts)
                    c["counters"].append({**base, "scope": "player", "have": _ref(have, consts)})
            elif scope == "detection":
                count = sum(1 for c in mates for e in c["p"].get("purchase_log") or [] if e["key"] in threat["counters"])
                need = max(4, round(duration / 60 / 5))
                team_findings.append({**base, "team": team, "scope": "team", "count": count, "need": need,
                                      "ok": count >= need,
                                      "slots": [c["slot"] for c in mates if c["pos"] in (4, 5)]})
            else:
                pool = [c for c in mates if scope == "team" or c["pos"] in CORE_POSITIONS]
                owners = [(c, _owned(c["p"], threat["counters"], consts)) for c in pool]
                owners = [(c, h) for c, h in owners if h]
                first = min(owners, key=lambda ch: ch[1][1]) if owners else None
                team_findings.append({**base, "team": team, "scope": "team", "ok": bool(first),
                                      "by": first[0]["hero"] if first else None,
                                      "by_slot": first[0]["slot"] if first else None,
                                      "have": _ref(first[1], consts) if first else None,
                                      "slots": [c["slot"] for c in pool]})
    return team_findings


def _ref(have, consts: Constants):
    if not have:
        return None
    key, t = have
    return {**consts.item_ref(key), "time": t, "time_fmt": fmt_time(t)}


def counter_score(ctx: dict) -> float | None:
    personal = ctx.get("counters") or []
    if not personal:
        return None
    return sum(1 for x in personal if x["have"]) / len(personal)


def counter_episodes(ctx: dict, make_episode, duration: int) -> list[dict]:
    out = []
    missing_meta = {m["key"] for m in (ctx.get("items") or {}).get("missing") or []}
    for x in ctx.get("counters") or []:
        enemies = ", ".join(x["enemies"])
        wanted = " / ".join(w["name"] for w in x["wanted"])
        if x["have"]:
            out.append(make_episode(ctx, x["have"]["time"], "Ответ на пик",
                                    "Предмет против сильной стороны вражеского пика",
                                    f"{ctx['hero']} — {x['have']['name']} на {x['have']['time_fmt']} против: {x['label']} "
                                    f"({enemies})", "good"))
        elif not any(w["key"] in missing_meta for w in x["wanted"]):
            out.append(make_episode(ctx, max(0, duration - 60), "Нет ответа на пик",
                                    "Против этого обычно покупают конкретные предметы — их не было",
                                    f"{ctx['hero']} — против «{x['label']}» ({enemies}) не было {wanted}", "disputed"))
    return out


def team_episodes(findings: list[dict], ctxs: list[dict], make_episode, duration: int) -> list[dict]:
    """Командные выводы: эпизод вешаем на того, кто купил ответ, или на саппортов/коров, если не купил никто."""
    by_slot = {c["slot"]: c for c in ctxs}
    team_name = {"radiant": "Силы Света", "dire": "Силы Тьмы"}
    out = []
    for f in findings:
        enemies = ", ".join(f["enemies"])
        wanted = " / ".join(w["name"] for w in f["wanted"])
        if f["threat"] == "invis":
            if f["ok"]:
                continue
            target = next((by_slot[s] for s in f["slots"] if s in by_slot), None)
            text = (f"{team_name[f['team']]} — против невидимости ({enemies}) куплено детекта: {f['count']} "
                    f"(сентри, пыль, гем), ждали хотя бы {f['need']}")
            out.append(make_episode(target, 600, "Мало детекта", "Против невидимок команде нужен детект", text,
                                    "disputed"))
            continue
        if f["ok"]:
            c = by_slot.get(f["by_slot"])
            out.append(make_episode(c, f["have"]["time"], "Ответ на пик", "Командный ответ на сильную сторону врага",
                                    f"{f['by']} — {f['have']['name']} на {f['have']['time_fmt']} против: {f['label']} "
                                    f"({enemies})", "good"))
        else:
            out.append(make_episode(None, max(0, duration - 60), "Нет ответа на пик",
                                    "Против этого обычно покупают конкретные предметы — их не было ни у кого",
                                    f"{team_name[f['team']]} — против «{f['label']}» ({enemies}) никто не купил {wanted}",
                                    "fact"))
    return out
