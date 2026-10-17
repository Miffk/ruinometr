"""Сборка полного разбора матча из данных OpenDota."""

from ..config import ANALYSIS_VERSION
from ..constants import Constants, rank_name
from . import episodes as ep
from . import counters as counters_mod
from . import mode
from . import scoring
from . import turbo as turbo_mod
from .core import (LANE_OPPONENT_POS, POS_LABELS, assign_positions, fmt_time, lane_result, team_of)
from .conduct import map_players, player_conduct
from .items import compare_build
from .mapdata import build_map
from .replay_signals import player_signals
from .skills import compare_skills

LANE_NAMES = {"top": "верх", "mid": "мид", "bot": "низ"}


def _building_label(key: str) -> tuple[str, str] | None:
    """npc_dota_badguys_tower1_top → ('dire', 'башня t1 · верх')."""
    if key.startswith("npc_dota_goodguys_"):
        team, rest = "radiant", key[len("npc_dota_goodguys_"):]
    elif key.startswith("npc_dota_badguys_"):
        team, rest = "dire", key[len("npc_dota_badguys_"):]
    else:
        return None
    parts = rest.split("_")
    lane = LANE_NAMES.get(parts[-1])
    if rest.startswith("tower"):
        tier = rest[5:6]
        return team, f"башня t{tier}" + (f" · {lane}" if lane else "")
    if rest.startswith("melee_rax"):
        return team, f"барак ближнего боя · {lane}"
    if rest.startswith("range_rax"):
        return team, f"барак дальнего боя · {lane}"
    if rest == "fort":
        return team, "Трон"
    return None


def _objectives(match: dict, ctx_by_slot: dict) -> list[dict]:
    out = []
    for o in match.get("objectives") or []:
        t = int(o.get("time", 0))
        typ = o.get("type")
        if typ == "building_kill":
            parsed = _building_label(o.get("key", ""))
            if not parsed:
                continue
            team, label = parsed
            out.append({"time": t, "team": team, "kind": "building", "label": label,
                        "text": f"{'Силы Света' if team == 'radiant' else 'Силы Тьмы'} потеряли: {label}"})
        elif typ == "CHAT_MESSAGE_ROSHAN_KILL":
            team = "radiant" if o.get("team") == 2 else "dire"
            out.append({"time": t, "team": team, "kind": "roshan", "label": "Рошан",
                        "text": f"{'Силы Света' if team == 'radiant' else 'Силы Тьмы'} убили Рошана"})
        elif typ == "CHAT_MESSAGE_AEGIS":
            c = ctx_by_slot.get(o.get("player_slot"))
            if c:
                out.append({"time": t, "team": c["team"], "kind": "aegis", "label": "Аегис",
                            "text": f"{c['hero']} поднял Аегис"})
        elif typ == "CHAT_MESSAGE_FIRSTBLOOD":
            c = ctx_by_slot.get(o.get("player_slot"))
            if c:
                out.append({"time": t, "team": c["team"], "kind": "firstblood", "label": "Первая кровь",
                            "text": f"Первая кровь — {c['hero']}"})
        elif typ == "CHAT_MESSAGE_COURIER_LOST":
            team = "radiant" if o.get("team") == 2 else "dire"
            out.append({"time": t, "team": team, "kind": "courier", "label": "Курьер",
                        "text": f"{'Силы Света' if team == 'radiant' else 'Силы Тьмы'} потеряли курьера"})
    out.sort(key=lambda x: x["time"])
    return out


def _chat(match: dict, ctx_by_slot: dict, consts: Constants) -> list[dict]:
    out = []
    for c in match.get("chat") or []:
        ctx = ctx_by_slot.get(c.get("player_slot"))
        if c.get("type") == "chat":
            text, kind = c.get("key", ""), "all"
        elif c.get("type") == "chatwheel":
            text, kind = consts.chat_wheel_text(c.get("key")), "wheel"
        else:
            continue
        out.append({"time": int(c.get("time", 0)), "time_fmt": fmt_time(c.get("time", 0)), "kind": kind, "text": text,
                    "name": ctx["name"] if ctx else c.get("unit"), "hero": ctx["hero"] if ctx else None,
                    "team": ctx["team"] if ctx else None})
    return out


def _avg_rank(players: list[dict]) -> str | None:
    lin = []
    for p in players:
        rt = p.get("rank_tier")
        if not rt:
            continue
        medal, stars = divmod(int(rt), 10)
        lin.append(35 if medal >= 8 else (medal - 1) * 5 + max(stars, 1) - 1)
    if not lin:
        return None
    avg = round(sum(lin) / len(lin))
    if avg >= 35:
        return rank_name(80)
    medal, star = divmod(avg, 5)
    return rank_name((medal + 1) * 10 + star + 1)


def _turbo_notes() -> list[str]:
    P = mode.P
    return [
        f"Это турбо: всё сравнивается со свежими турбо-матчами тех же героев на вашем ранге, а не с про и не с обычными играми. "
        f"Процентили GPM, урона, добиваний и смертей — по турбо-выборке.",
        f"Что собирают и как качают — по турбо-игрокам (итоговые предметы и прокачка). Тайминги покупок в турбо-выборке "
        f"OpenDota не отдаёт, поэтому они — оценка: тайминг про × темп турбо (золото копится в ~{1 / P.pace:.1f} раза быстрее).",
        f"Окна под турбо: линия — до {P.lane_minute}:00, финал — последние {P.final_window // 60} мин, "
        f"«деньги в кармане» — от {P.pocket_gold} золота, разгром — от {P.stomp_gold} разницы.",
    ]


def build_report(match: dict, consts: Constants, metas: dict[int, dict | None], parsed: dict | None = None,
                 replay_reason: str | None = None, turbo: dict | None = None) -> dict:
    duration = int(match.get("duration") or 0)
    players = match["players"]

    # Режим выставляем до любых расчётов: от него зависят окна линии, пороги и с кем сравниваем.
    is_turbo = mode.is_turbo_match(match)
    paces = (turbo or {}).get("paces") or {}
    if is_turbo:
        known = sorted(v for v in paces.values() if v)
        mode.use(mode.turbo(known[len(known) // 2] if known else 0.55))
    else:
        mode.use(mode.NORMAL)
    pool = ((turbo or {}).get("pool") or {}).get("samples") or {}
    positions = assign_positions(players)

    ctxs = []
    for idx, p in enumerate(players):
        ctxs.append({
            "p": p, "idx": idx, "slot": p["player_slot"], "team": team_of(p), "pos": positions[p["player_slot"]],
            "hero": consts.hero_name(p["hero_id"]), "name": p.get("personaname") or "Аноним",
        })
    by_team_pos = {(c["team"], c["pos"]): c for c in ctxs}
    ctx_by_slot = {c["slot"]: c for c in ctxs}

    team_kills = {t: sum(c["p"].get("kills") or 0 for c in ctxs if c["team"] == t) for t in ("radiant", "dire")}
    team_nw = {t: sum(c["p"].get("net_worth") or 0 for c in ctxs if c["team"] == t) for t in ("radiant", "dire")}
    team_dmg = {t: sum(c["p"].get("hero_damage") or 0 for c in ctxs if c["team"] == t) for t in ("radiant", "dire")}
    objectives = _objectives(match, ctx_by_slot)

    replay_players = map_players(parsed, match) if parsed else {}
    if parsed:
        # Сверяем, что игрок реплея — тот же герой, что в OpenDota; иначе данные реплея не используем.
        for c in ctxs:
            rp = replay_players.get(c["slot"])
            npc = consts.heroes.get(c["p"]["hero_id"], {}).get("name", "")
            if not rp or player_conduct(rp, match, c["slot"], duration)["hero_check"] !=                     npc.replace("npc_dota_hero_", "").replace("_", "").lower():
                replay_players, parsed = {}, None
                replay_reason = "герои в реплее не совпали с OpenDota"
                break

    for c in ctxs:
        p = c["p"]
        enemy = "dire" if c["team"] == "radiant" else "radiant"
        opp = by_team_pos.get((enemy, LANE_OPPONENT_POS[c["pos"]]))
        c["opp_hero"] = opp["hero"] if opp else None
        c["opp_slot"] = opp["slot"] if opp else None
        c["lane"] = lane_result(p, opp["p"] if opp else None) if duration >= 600 else None
        c["kp"] = ((p.get("kills") or 0) + (p.get("assists") or 0)) / team_kills[c["team"]] if team_kills[c["team"]] else 0
        c["dead_s"] = p.get("life_state_dead") or 0
        c["dead_pct"] = c["dead_s"] / duration if duration else 0
        c["nw_share"] = (p.get("net_worth") or 0) / team_nw[c["team"]] if team_nw[c["team"]] else 0
        c["dmg_share"] = (p.get("hero_damage") or 0) / team_dmg[c["team"]] if team_dmg[c["team"]] else 0
        c["team_losses"] = [o for o in objectives if o["team"] == c["team"] and o["kind"] == "building"]
        c["fights"] = None
        if is_turbo:
            samples = pool.get(p["hero_id"]) or []
            hero_pace = paces.get(p["hero_id"]) or mode.P.pace
            c["bench"] = turbo_mod.benchmarks(p, duration, samples) if len(samples) >= 3 else None
            c["items"] = turbo_mod.compare_build_turbo(p, duration, samples, metas.get(p["hero_id"]), hero_pace, consts)
            c["skills"] = compare_skills(p, c["pos"], turbo_mod.skills_meta(samples), consts)
            c["skills"]["ref"] = "турбо-игроков"
        else:
            c["bench"] = None
            c["items"] = compare_build(p, c["pos"], duration, metas.get(p["hero_id"]), consts)
            c["skills"] = compare_skills(p, c["pos"], metas.get(p["hero_id"]), consts)
        c["rp"] = replay_players.get(c["slot"])
        c["conduct"] = player_conduct(c["rp"], match, c["slot"], duration)
        c["signals"] = player_signals(c, match, parsed, consts) if parsed else {"available": False}

    team_counters = counters_mod.analyze(ctxs, consts, duration)
    episodes = ep.collect(ctxs, match, duration, team_counters)

    for c in ctxs:
        c["components"] = scoring.components(c, duration)
        c["score"] = scoring.score(c, c["components"])
    scoring.assign_verdicts(ctxs)

    radiant_win = bool(match.get("radiant_win"))
    winner = "radiant" if radiant_win else "dire"
    mvp = max((c for c in ctxs if c["team"] == winner), key=lambda c: c["score"])
    questionable = [c["hero"] for c in ctxs if c["verdict"] == "questionable"]

    adv = match.get("radiant_gold_adv") or []
    final_adv = abs(adv[-1]) if adv else 0
    # Счёт как в клиенте — сумма убийств героев (radiant_score у OpenDota иногда учитывает и прочие смерти).
    rs, ds = team_kills["radiant"], team_kills["dire"]
    loser_max = max((-a if radiant_win else a) for a in adv) if adv else 0
    if loser_max >= mode.P.comeback_gold:
        label = "Камбэк"
    elif final_adv >= mode.P.stomp_gold or max(rs, ds) >= 3 * max(min(rs, ds), 1):
        label = "Разгром"
    elif final_adv >= mode.P.confident_gold:
        label = "Уверенная победа"
    else:
        label = "Ровная игра"

    out_players = []
    for c in sorted(ctxs, key=lambda c: (c["team"] != "radiant", c["pos"])):
        p = c["p"]
        reasons = [e for e in episodes if e["slot"] == c["slot"] and
                   (e["severity"] in ep.BAD_SEVERITIES if c["verdict"] == "questionable" else
                    e["severity"] == "good" if c["verdict"] == "carried" else True)]
        out_players.append({
            "slot": c["slot"], "team": c["team"], "name": c["name"], "account_id": p.get("account_id"),
            "rank": rank_name(p.get("rank_tier")),
            "hero_id": p["hero_id"], "hero": c["hero"], "hero_img": consts.hero_img(p["hero_id"]),
            "pos": c["pos"], "pos_label": POS_LABELS[c["pos"]],
            "kills": p.get("kills"), "deaths": p.get("deaths"), "assists": p.get("assists"),
            "last_hits": p.get("last_hits"), "denies": p.get("denies"), "level": p.get("level"),
            "gpm": p.get("gold_per_min"), "xpm": p.get("xp_per_min"), "net_worth": p.get("net_worth"),
            "hero_damage": p.get("hero_damage"), "tower_damage": p.get("tower_damage"),
            "kp": round(c["kp"] * 100), "nw_share": round(c["nw_share"] * 100), "dmg_share": round(c["dmg_share"] * 100),
            "dead_s": c["dead_s"], "dead_fmt": fmt_time(c["dead_s"]), "dead_pct": round(c["dead_pct"] * 100),
            "lane": c["lane"], "lane_opponent": c["opp_hero"], "fights": c["fights"],
            "score": c["score"], "team_median": c["team_median"], "verdict": c["verdict"],
            "verdict_label": c["verdict_label"], "confidence": c["confidence"], "is_mvp": c is mvp,
            "components": c["components"], "reasons": reasons[:6],
            "items": c["items"],
            "final_items": [consts.item_ref(key) for key in
                            (consts.item_key_by_id.get(p.get(f"item_{i}")) for i in range(6)) if key],
            "obs_placed": p.get("obs_placed"), "sen_placed": p.get("sen_placed"), "stuns": p.get("stuns"),
            "camps_stacked": p.get("camps_stacked"),
            "conduct": {k: v for k, v in c["conduct"].items() if k != "hero_check"},
            "signals": c["signals"],
            "counters": c["counters"],
            "skills": c["skills"],
        })

    map_data = None
    if parsed:
        map_data = build_map(parsed, ctxs, objectives, match, duration)
        for d in map_data["deaths"]:
            d["killer"] = consts.hero_name_by_npc(d["killer"]) if (d["killer"] or "").startswith("npc_dota_hero_") \
                else ("крипы/строение" if d["killer"] else None)

    summary = f"MVP — {mvp['hero']}." + (f" Под вопросом — {', '.join(questionable)}" if questionable else " Явных руинеров нет")

    return {
        "analysis_version": ANALYSIS_VERSION,
        "match_id": match["match_id"], "start_time": match.get("start_time"),
        "duration": duration, "duration_fmt": fmt_time(duration),
        "radiant_win": radiant_win, "radiant_score": rs, "dire_score": ds,
        "label": label, "avg_rank": _avg_rank(players), "summary": summary,
        "gold_adv": adv, "xp_adv": match.get("radiant_xp_adv") or [],
        "objectives": [{**o, "time_fmt": fmt_time(o["time"])} for o in objectives],
        "players": out_players, "episodes": episodes, "chat": _chat(match, ctx_by_slot, consts),
        "replay": {"available": parsed is not None, "reason": replay_reason},
        "mode": {
            "key": mode.P.key, "label": mode.P.label, "game_mode": match.get("game_mode"),
            "game_mode_name": mode.GAME_MODES.get(match.get("game_mode"), f"режим {match.get('game_mode')}"),
            "pace": round(mode.P.pace, 2), "lane_minute": mode.P.lane_minute,
            "turbo_samples": {consts.hero_name(h): len(v) for h, v in pool.items()} if is_turbo else None,
            "rank_band": ((turbo or {}).get("pool") or {}).get("band") if is_turbo else None,
        },
        "map": map_data,
        "counters_team": team_counters,
        "deaths": sorted(
            ({"time": int(d["time"]), "time_fmt": fmt_time(d["time"]), "team": c["team"], "hero": c["hero"],
              "slot": c["slot"], "killer": consts.hero_name_by_npc(d["key"]) if (d.get("key") or "").startswith(
                  "npc_dota_hero_") else None}
             for c in ctxs for d in c["p"].get("deaths_log") or []),
            key=lambda d: d["time"]),
        "notes": [
            "Факты — из реплея (через OpenDota и свой парсер); вердикты — формула поверх фактов, "
            "это вопрос, а не приговор.",
        ] + (_turbo_notes() if is_turbo else [
            "Закуп сравнивается со свежими матчами лиг на том же герое (и позиции, если игр хватает). "
            "У про другой темп игры: опоздание на пару минут в паблике — норма.",
        ]) + [
            "AFK — отрезки от 90 с, когда герой жив, а игрок не отдал ни одного приказа. "
            "Время мёртвым не считается: ждать респаун — не AFK.",
            "С патча 10.07.2026 Valve не пишет в реплей, кто кого репортил. Порядочность и вежливость — "
            "полосы на момент матча, а не итог этой игры.",
        ] + ([f"Свой разбор реплея не сделан: {replay_reason}. AFK, таблица и порядочность недоступны."]
             if parsed is None and replay_reason else []),
    }
