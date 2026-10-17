"""Эпизоды: правила над фактами из реплея. Каждый эпизод — момент матча с таймкодом и пояснением."""

from . import mode
from .core import (CORE_POSITIONS, death_times, fights_after, fmt_time, in_any_fight, plural, stage_of,
                   took_part)


from .counters import counter_episodes, team_episodes
from .replay_signals import signal_episodes
from .skills import skill_episodes


def deaths_word(n):
    return plural(n, "смерть", "смерти", "смертей")

BAD_SEVERITIES = {"bad", "disputed"}


def _ep(ctx, time, title, rule, text, severity, end=None):
    return {
        "slot": ctx["slot"] if ctx else None,
        "hero": ctx["hero"] if ctx else None,
        "time": int(time),
        "time_fmt": fmt_time(time),
        "end": int(end) if end is not None else None,
        "end_fmt": fmt_time(end) if end is not None else None,
        "title": title,
        "rule": rule,
        "text": text,
        "severity": severity,
    }


def lane_episodes(ctx) -> list[dict]:
    lane = ctx["lane"]
    if not lane:
        return []
    hero, opp = ctx["hero"], ctx["opp_hero"]
    out = []
    core = ctx["pos"] in CORE_POSITIONS
    # Смерти без размена — повод, только если по опыту линия тоже не выиграна.
    lost = (lane["xp_diff"] <= -1000 or (core and lane["lh_diff"] <= -15)
            or (lane["deaths_unanswered"] >= 2 and lane["xp_diff"] < 300))
    if lost:
        parts = []
        if core or lane["lh_diff"] <= -15:
            parts.append(f"{lane['lh_diff']:+d} ластхитов")
        parts.append(f"{lane['xp_diff']:+d} опыта")
        if lane["deaths_unanswered"]:
            parts.append(f"{deaths_word(lane['deaths_unanswered'])} без размена")
        out.append(_ep(ctx, mode.P.lane_end - 1, "Слил лайн", f"Итог линии к {mode.P.lane_minute}:00: минус по LH, XP или смерти без размена",
                       f"{hero} — итог линии к {mode.P.lane_minute}:00 против {opp}: {', '.join(parts)}", "disputed"))
    if core and lane["lh_diff"] >= 20:
        out.append(_ep(ctx, mode.P.lane_end - 1, "Фарм-машина", f"Разница по ластхитам с соперником по линии к {mode.P.lane_minute}:00",
                       f"{hero} — {lane['lh']} ластхитов к {mode.P.lane_minute}:00 против {lane['opp_lh']} у {opp}: по фарму линия за ним",
                       "good"))
    if lane["xp_diff"] >= 1000:
        out.append(_ep(ctx, mode.P.lane_end - 1, "Перекач", f"Опережение по опыту над соперником по линии к {mode.P.lane_minute}:00",
                       f"{hero} — опережение по опыту над {opp} на {lane['xp_diff']} к {mode.P.lane_minute}:00", "good"))
    return out


def death_episodes(ctx, team_ctxs, match, duration) -> list[dict]:
    p = ctx["p"]
    hero = ctx["hero"]
    out = []
    deaths = death_times(p)
    team_deaths = sum(c["p"].get("deaths") or 0 for c in team_ctxs)

    worst = max(team_ctxs, key=lambda c: c["dead_s"])
    if worst is ctx and ctx["dead_pct"] >= 0.2 and deaths:
        lost_gold = sum(d.get("gold_lost") or 0 for d in p.get("deaths_log") or [])
        out.append(_ep(ctx, deaths[0], "Жил в таверне", "Больше всех в команде времени мёртвым (доля матча)",
                       f"{hero} — {fmt_time(ctx['dead_s'])} на респауне ({round(ctx['dead_pct'] * 100)}% матча, "
                       f"больше всех в команде); на смертях потеряно {lost_gold} золота", "disputed"))

    n = p.get("deaths") or 0
    if n >= 8 and team_deaths and n / team_deaths >= 0.25:
        late = [t for t in deaths if t >= mode.P.lane_end] or deaths
        out.append(_ep(ctx, late[0], "Главный фидер", "Много смертей: большая доля смертей команды",
                       f"{hero} — {deaths_word(n)} ({round(n / team_deaths * 100)}% смертей команды), при этом "
                       f"{plural(p.get('kills', 0), 'убийство', 'убийства', 'убийств')} и "
                       f"{plural(p.get('assists', 0), 'ассист', 'ассиста', 'ассистов')}", "disputed", end=late[-1]))

    solo = [t for t in deaths if t >= mode.P.lane_end and not in_any_fight(match, t)]
    if len(solo) >= 3:
        out.append(_ep(ctx, solo[0], "Пойман в соло", f"Смерти после {mode.P.lane_minute}:00 вне командных драк",
                       f"{hero} — {deaths_word(len(solo))} вне драк после {mode.P.lane_minute}:00 "
                       f"({', '.join(fmt_time(t) for t in solo[:5])}{'…' if len(solo) > 5 else ''})",
                       "disputed", end=solo[-1]))

    for bb in p.get("buyback_log") or []:
        t = int(bb.get("time", 0))
        again = next((d for d in deaths if t < d <= t + 60), None)
        if again is None:
            continue
        text = f"{hero} — байбек на {fmt_time(t)} и повторная смерть через {again - t} с"
        lost = next((o for o in ctx["team_losses"] if again <= o["time"] <= again + 60), None)
        if lost:
            text += f"; следом команда потеряла: {lost['label']}"
        out.append(_ep(ctx, t, "Байбек в таверну", "Байбек и повторная смерть в течение минуты", text, "disputed",
                       end=again))
    return out


def fight_episodes(ctx, match) -> list[dict]:
    fights = fights_after(match, mode.P.lane_end)
    if len(fights) < 4:
        return []
    part = sum(1 for f in fights if took_part(f, ctx["idx"]))
    ctx["fights"] = {"part": part, "total": len(fights)}
    if part / len(fights) < 0.4:
        return [_ep(ctx, fights[0]["start"], "Явка на драки", f"Доля командных драк после {mode.P.lane_minute}:00, где игрок участвовал",
                    f"{ctx['hero']} — участвовал в {part} из {len(fights)} драк после {mode.P.lane_minute}:00", "disputed",
                    end=fights[-1]["end"])]
    return []


def afk_episodes(ctx) -> list[dict]:
    conduct = ctx.get("conduct") or {}
    out = []
    for w in conduct.get("afk") or []:
        text = f"{ctx['hero']} — {w['duration_fmt']} подряд без зарегистрированных приказов с {w['start_fmt']}"
        if w["stood_still"]:
            text += "; герой стоял на месте"
        out.append(_ep(ctx, w["start"], "Отошёл за чаем",
                       "Долго без зарегистрированных приказов (≥ 90 с подряд, пока герой жив)", text, "disputed",
                       end=w["end"]))
    return out


def _turbo_item_episodes(ctx, items, n_games, duration) -> list[dict]:
    """Турбо: состав — против турбо-игроков, тайминги — оценка (тайминг про × темп турбо)."""
    hero = ctx["hero"]
    pace = items.get("pace")
    out = []
    for e in items["late"]:
        out.append(_ep(ctx, e["time"], f"Поздний {e['name']}",
                       "Заметно позже оценки для турбо (тайминг про × темп турбо)",
                       f"{hero} — {e['name']} на {e['time_fmt']}, для турбо ожидали около {e['pro_median_fmt']} "
                       f"(тайминг про × {pace})", "disputed"))
    for e in items["missing"]:
        out.append(_ep(ctx, e["median"] if e["median"] is not None else duration - 60, f"Без {e['name']}",
                       "Турбо-игроки на этом герое почти всегда его собирают",
                       f"{hero} — не собрал {e['name']}: у турбо-игроков в похожих по длине играх он в {e['share']}% "
                       f"из {n_games}, а матч длился {fmt_time(duration)}", "disputed"))
    if items.get("score") is not None and items["score"] >= 0.85 and len(items["core"]) >= 2:
        names = ", ".join(c["name"] for c in items["core"][:4])
        times = [c["bought_at"] for c in items["core"] if c.get("bought_at") is not None]
        out.append(_ep(ctx, max(times) if times else duration, "Закуп по мете",
                       "Собрал то, что обычно берут турбо-игроки на этом герое",
                       f"{hero} — {names}, как у турбо-игроков ({n_games})", "good"))
    return out


def item_episodes(ctx, duration) -> list[dict]:
    items = ctx.get("items") or {}
    if not items.get("available"):
        return []
    hero = ctx["hero"]
    n = items["samples"]
    n_games = plural(n, "игры", "игр", "игр")
    if items.get("turbo"):
        return _turbo_item_episodes(ctx, items, n_games, duration)
    basis = "на этой позиции" if items["basis"] == "pos" else "на герое"
    out = []
    for e in items["late"]:
        out.append(_ep(ctx, e["time"], f"Поздний {e['name']}", "Ключевой предмет заметно позже, чем у про",
                       f"{hero} — {e['name']} на {e['time_fmt']}, у про {basis} медиана {e['pro_median_fmt']} "
                       f"(берут в {e['pro_share']}% из {n_games})", "disputed"))
    for e in items["missing"]:
        out.append(_ep(ctx, e["median"], f"Без {e['name']}", "Про почти всегда собирают этот предмет к этому времени",
                       f"{hero} — не собрал {e['name']}: у про {basis} он в {e['share']}% из {n_games}, медиана "
                       f"{e['median_fmt']}, а матч длился {fmt_time(duration)}", "disputed"))
    reachable = [c for c in items["core"] if c["median"] + 120 < duration]
    if items.get("score") is not None and items["score"] >= 0.85 and len(reachable) >= 2:
        names = ", ".join(c["name"] for c in reachable[:4])
        out.append(_ep(ctx, reachable[-1]["median"], "Закуп по мете", "Коровые предметы про — вовремя",
                       f"{hero} — {names} в тайминги про-игроков {basis} ({n_games})", "good"))
    return out


def standout_episodes(ctxs, duration) -> list[dict]:
    """Хорошие эпизоды: лучший в матче по урону, строениям, обзору; ни одной смерти."""
    out = []
    best_dmg = max(ctxs, key=lambda c: c["p"].get("hero_damage") or 0)
    out.append(_ep(best_dmg, duration, "Главный дамагер", "Больше всех урона по героям в матче",
                   f"{best_dmg['hero']} — {best_dmg['p'].get('hero_damage', 0)} урона по героям "
                   f"({round(best_dmg['dmg_share'] * 100)}% урона команды)", "good"))
    best_tower = max(ctxs, key=lambda c: c["p"].get("tower_damage") or 0)
    if (best_tower["p"].get("tower_damage") or 0) >= 3000:
        out.append(_ep(best_tower, duration, "Сносил строения", "Больше всех урона по строениям",
                       f"{best_tower['hero']} — урона по строениям: {best_tower['p'].get('tower_damage')}", "good"))

    def vision(c):
        p = c["p"]
        return (p.get("obs_placed") or 0) + (p.get("observer_kills") or 0) + (p.get("sentry_kills") or 0)

    best_vision = max(ctxs, key=vision)
    if vision(best_vision) >= 5:
        p = best_vision["p"]
        out.append(_ep(best_vision, duration, "Вардмастер", "Больше всех обзора: обсерверы поставлены, варды врага сняты",
                       f"{best_vision['hero']} — обсерверов поставлено: {p.get('obs_placed') or 0}, "
                       f"вражеских вардов снято: {(p.get('observer_kills') or 0) + (p.get('sentry_kills') or 0)}",
                       "good"))
    if duration >= 20 * 60:
        for c in ctxs:
            if (c["p"].get("deaths") or 0) == 0:
                out.append(_ep(c, duration, "Ни одной смерти", "Весь матч без смертей",
                               f"{c['hero']} — 0 смертей за {fmt_time(duration)}", "good"))
    return out


def match_episodes(match, duration) -> list[dict]:
    adv = match.get("radiant_gold_adv") or []
    if len(adv) < 10:
        return []
    radiant_win = bool(match.get("radiant_win"))
    sign = 1 if radiant_win else -1
    winner = "Силы Света" if radiant_win else "Силы Тьмы"
    out = []
    lead_since = None
    for m in range(len(adv) - 1, -1, -1):
        if adv[m] * sign > 0:
            lead_since = m
        else:
            break
    if lead_since is not None and lead_since * 60 <= duration - 5 * 60:
        out.append(_ep(None, lead_since * 60, "Перелом", "С этой минуты победитель не отдавал лидерство по золоту",
                       f"С {lead_since}:00 {winner} впереди по золоту до конца матча "
                       f"(максимум +{max(a * sign for a in adv)})", "fact"))
    loser_max = max(-a * sign for a in adv)
    if loser_max >= mode.P.comeback_gold:
        m = max(range(len(adv)), key=lambda i: -adv[i] * sign)
        out.append(_ep(None, m * 60, "Камбэк", f"Проигравшие вели по золоту на {mode.P.comeback_gold}+",
                       f"Проигравшая команда вела на {loser_max} золота к {m}:00 — и отдала игру", "fact"))
    return out


def collect(ctxs, match, duration, team_counters=()) -> list[dict]:
    episodes = []
    for c in ctxs:
        team = [o for o in ctxs if o["team"] == c["team"]]
        episodes += lane_episodes(c)
        episodes += death_episodes(c, team, match, duration)
        episodes += fight_episodes(c, match)
        episodes += item_episodes(c, duration)
        episodes += afk_episodes(c)
        episodes += signal_episodes(c, _ep)
        episodes += counter_episodes(c, _ep, duration)
        episodes += skill_episodes(c, _ep)
    episodes += team_episodes(list(team_counters), ctxs, _ep, duration)
    episodes += standout_episodes(ctxs, duration)
    episodes += match_episodes(match, duration)
    for e in episodes:
        e["stage"] = stage_of(e["time"], duration)
    episodes.sort(key=lambda e: (e["time"], e["slot"] if e["slot"] is not None else -1))
    for c in ctxs:
        c["bad_episodes"] = sum(1 for e in episodes if e["slot"] == c["slot"] and e["severity"] in BAD_SEVERITIES
                                and not e.get("minor"))
    return episodes
