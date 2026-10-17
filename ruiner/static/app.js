"use strict";

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n) => (n ?? 0).toLocaleString("ru-RU");

const SEV = { bad: ["critical", "Плохо"], disputed: ["warning", "Спорно"], good: ["good", "Хорошо"], fact: ["info", "Факт"] };
const STAGES = { lane: "Линия · 0:00–10:00", mid: "Мидгейм", final: "Финал · последние 5 минут" };
const TEAM = { radiant: "Силы Света", dire: "Силы Тьмы" };
const VERDICT = { carried: ["good", "★ Тащил"], ok: ["neutral", "Норм"], questionable: ["warning", "? Под вопросом"] };
const ITEM_STATUS = { late: "позже про", on_time: "в тайминг", early: "раньше про", offmeta: "не как у про", alt: "другие сапоги", unknown: "нет данных" };

const state = { report: null, open: new Set(), tab: {}, epFilter: "all", chatFilter: "all" };

// ---------- тема ----------

function storedTheme() {
  try { return localStorage.getItem("ruiner-theme"); } catch { return null; }
}
function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  const dark = theme ? theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  $("#theme-toggle").innerHTML = dark
    ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
    : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
  $("#theme-toggle").title = dark ? "Светлая тема" : "Тёмная тема";
}
$("#theme-toggle").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = dark ? "light" : "dark";
  try { localStorage.setItem("ruiner-theme", next); } catch { /* приватный режим — тема не запомнится */ }
  applyTheme(next);
  if (state.report && !$("#match").hidden) render();
});
applyTheme(storedTheme());

// ---------- навигация ----------

function route() {
  const m = location.pathname.match(/^\/match\/(\d+)/);
  if (m) { $("#query").value = m[1]; load(m[1]); }
  else show("home");
}
function show(id) {
  for (const s of ["home", "status", "match"]) $("#" + s).hidden = s !== id;
}
function go(text) {
  const m = String(text).match(/\d{8,12}/);
  if (!m) { alert("Не нашёл ID матча — нужно число вроде 9046870406 или ссылка на матч"); return; }
  history.pushState({}, "", `/match/${m[0]}`);
  route();
}
$("#search").addEventListener("submit", (e) => { e.preventDefault(); go($("#query").value); });
$("#home-search").addEventListener("submit", (e) => { e.preventDefault(); go($("#home-query").value); });
window.addEventListener("popstate", route);

// ---------- загрузка ----------

let pollTimer = null;
async function load(id, refresh = false) {
  clearTimeout(pollTimer);
  show("status");
  $("#status").classList.remove("error");
  try {
    const r = await fetch(`/api/analyze/${id}${refresh ? "?refresh=1" : ""}`);
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || r.statusText);
    if (body.state === "error") throw new Error(body.error);
    if (body.state === "done") {
      state.report = body.result; state.open = new Set(); state.tab = {};
      RuinerMap.reset(); render(); window.scrollTo(0, 0); return;
    }
    $("#status-msg").textContent = body.message;
    $("#status-bar").style.width = `${Math.round(body.progress * 100)}%`;
    pollTimer = setTimeout(() => load(id), 1500);
  } catch (err) {
    $("#status").classList.add("error");
    $("#status-msg").textContent = err.message;
  }
}

// ---------- рендер ----------

function render() {
  const r = state.report;
  document.title = `Матч ${r.match_id}: ${r.summary}`;
  $("#match").innerHTML = [
    heroCard(r), sectionNav(r), MatchChart.panel(r), RuinerMap.panel(r), playersPanel(r), episodesPanel(r), conductPanel(r),
    `<div class="two-col" id="sec-feed">${objectivesPanel(r)}${chatPanel(r)}</div>`, notesPanel(r),
  ].join("");
  show("match");
  bind();
}

function rerenderChart() {
  const old = $("#sec-flow");
  if (!old) return render();
  old.outerHTML = MatchChart.panel(state.report);
  MatchChart.mount(state.report, rerenderChart);
}

const heroOf = (slot) => state.report.players.find((p) => p.slot === slot);

function heroCard(r) {
  const winner = r.radiant_win ? "radiant" : "dire";
  const date = r.start_time ? new Date(r.start_time * 1000).toLocaleString("ru-RU", { dateStyle: "long", timeStyle: "short" }) : "";
  const mvp = r.players.find((p) => p.is_mvp);
  const questionable = r.players.filter((p) => p.verdict === "questionable");
  const side = (team, score, right) => `<div class="team-side${right ? " right" : ""}">
      <span class="name team-${team}">${TEAM[team]}</span>
      <span class="result">${(team === "radiant") === r.radiant_win ? "Победа" : "Поражение"}</span></div>`;
  return `<section class="panel match-hero">
    <div>
      <div class="match-meta"><span>Матч ${r.match_id}</span>${date ? `<span>${esc(date)}</span>` : ""}
        <a href="https://www.opendota.com/matches/${r.match_id}" target="_blank" rel="noopener">OpenDota ↗</a>
        <a href="https://www.dotabuff.com/matches/${r.match_id}" target="_blank" rel="noopener">Dotabuff ↗</a>
        <a href="#" id="refresh">Пересобрать</a></div>
      <h1 class="match-title">${esc(r.summary)}</h1>
      <div class="scoreline">
        ${side("radiant")}
        <div class="score"><span class="team-radiant">${r.radiant_score}</span><span class="sep">:</span><span class="team-dire">${r.dire_score}</span></div>
        ${side("dire", null, true)}
      </div>
      <div class="match-facts">
        <span class="pill ${winner}">Победа — ${TEAM[winner]}</span>
        ${modePill(r)}
        <span class="pill neutral">⏱ ${r.duration_fmt}</span>
        <span class="pill neutral">${esc(r.label)}</span>
        ${r.avg_rank ? `<span class="pill neutral">Средний ранг: ${esc(r.avg_rank)}</span>` : ""}
        ${r.replay && r.replay.available ? '<span class="pill info">Свой разбор реплея</span>' : ""}
      </div>
    </div>
    <div class="side-col">
      ${mvp ? `<div class="mvp-card"><img src="${esc(mvp.hero_img)}" alt="">
        <div><div class="label">MVP</div><div class="hero-name">${esc(mvp.hero)}</div>
        <div class="muted small">${esc(mvp.name)} · вклад ${mvp.score}/100 · ${mvp.kills}/${mvp.deaths}/${mvp.assists}</div></div></div>` : ""}
      <div class="question-list"><div class="label">Под вопросом</div>
        ${questionable.length ? `<div class="mini-heroes">${questionable.map((p) => `<a href="#p-${p.slot}" class="mini-hero ${p.team}" data-open="${p.slot}">
          <img src="${esc(p.hero_img)}" alt="">${esc(p.hero)}</a>`).join("")}</div>` : '<div class="muted">Явных руинеров нет</div>'}
      </div>
    </div>
  </section>`;
}

function modePill(r) {
  const m = r.mode;
  if (!m) return "";
  if (m.key === "turbo") {
    return `<span class="pill warning" title="Нормы, закуп и прокачка — по турбо-матчам тех же героев на вашем ранге. Темп турбо ≈ ${m.pace}: золото копится в ~${(1 / m.pace).toFixed(1)} раза быстрее.">⚡ Турбо · сравнение с турбо-игроками</span>`;
  }
  return `<span class="pill neutral">${esc(m.game_mode_name)}</span>`;
}

function sectionNav(r) {
  const links = [["sec-flow", "Ход матча"], r.map ? ["map-panel", "Карта"] : null, ["sec-players", "Игроки"], ["sec-episodes", `Эпизоды · ${r.episodes.length}`],
    r.replay ? ["sec-conduct", "Поряда"] : null, ["sec-feed", "Строения и чат"]].filter(Boolean);
  return `<nav class="section-nav">${links.map(([id, t]) => `<a href="#${id}">${t}</a>`).join("")}</nav>`;
}

// ---------- игроки ----------

function playersPanel(r) {
  const block = (team) => {
    const ps = r.players.filter((p) => p.team === team);
    const kills = ps.reduce((s, p) => s + p.kills, 0);
    const nw = ps.reduce((s, p) => s + (p.net_worth || 0), 0);
    const won = (team === "radiant") === r.radiant_win;
    return `<div class="team-block"><div class="team-head ${team}"><span>${TEAM[team]} · ${won ? "Победа" : "Поражение"}</span>
      <span class="meta">${kills} убийств · нетворс ${num(nw)}</span></div>${ps.map(playerRow).join("")}</div>`;
  };
  return `<section class="panel" id="sec-players">
    <div class="panel-head"><div><h2>Игроки</h2>
      <p class="sub">Оценка 0–100 — как игрок сыграл по сравнению с другими игроками на том же герое и позиции${r.mode && r.mode.key === "turbo"
        ? " <b>в турбо</b> (сравниваем только с турбо-играми)" : ""}. Чёрточка на полоске — средняя оценка его команды.
        Нажмите на игрока, чтобы увидеть подробности: из чего оценка, что купил и как качался.</p></div></div>
    ${verdictLegend()}
    ${block("radiant")}${block("dire")}</section>`;
}

const plural = (n, one, few, many) => {
  const a = Math.abs(n) % 100, b = a % 10;
  return `${n} ${a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many}`;
};

// Почему такой вердикт — простыми словами (сами правила — в ruiner/analysis/scoring.py, assign_verdicts).
function verdictWhy(p) {
  const s = p.score, avg = Math.round(p.team_median), bad = p.bad_episodes ?? 0;
  const mates = state.report.players.filter((o) => o.team === p.team && o.slot !== p.slot);
  const best = mates.reduce((a, o) => (o.score > (a ? a.score : -1) ? o : a), null);
  const own = `Оценка ${s} из 100, у остальных в команде — около ${avg}.`;
  let why;
  if (p.verdict === "carried") {
    why = `${own} Лучшая оценка в своей команде, с заметным отрывом.`;
  } else if (p.verdict === "questionable") {
    why = s < 20 ? `${own} Очень низкая оценка.`
      : `${own} Заметно слабее, чем у своих` + (s < 45 ? ", и сама оценка низкая." : `, и есть спорные моменты (${bad}).`) +
        " Это повод посмотреть эпизоды игрока, а не приговор.";
  } else if (s >= 68 && best && best.score > s) {
    why = s >= avg
      ? `${own} Хорошая игра, но у ${best.hero} ещё лучше (${best.score}), а «Тащил» — только один на команду.`
      : `${own} Хорошая оценка, просто команда в целом сыграла ещё сильнее (лучший — ${best.hero}, ${best.score}).`;
  } else if (s >= 68) {
    why = `${own} Лучшая оценка в команде, но отрыв от остальных слишком маленький для «Тащил».`;
  } else if (avg - s >= 10) {
    why = `${own} Чуть слабее, чем у своих, но сама оценка нормальная и спорных моментов почти нет.`;
  } else {
    why = `${own} Примерно на уровне остальных в своей команде.`;
  }
  const conf = { "почти наверняка": "всё однозначно", "вероятно": "скорее всего так", "похоже": "на грани, могло быть и по-другому" }[p.confidence];
  return conf ? `${why} Уверенность «${p.confidence}» — ${conf}.` : why;
}

function verdictLegend() {
  return `<div class="verdict-legend">
    <div><span class="pill good">★ Тащил</span> лучшая игра в своей команде, с заметным отрывом</div>
    <div><span class="pill neutral">Норм</span> на уровне остальных в своей команде</div>
    <div><span class="pill warning">? Под вопросом</span> заметно слабее своих — повод посмотреть эпизоды игрока, а не приговор</div>
    <div class="conf-row"><b>Подпись под оценкой</b> — насколько вердикт однозначный:
      <span class="chip-conf">почти наверняка</span> — всё очевидно ·
      <span class="chip-conf">вероятно</span> — скорее всего так ·
      <span class="chip-conf">похоже</span> — на грани, могло быть и по-другому.
      Наведите на оценку игрока, чтобы увидеть, почему так.</div>
  </div>`;
}

function meterColor(v) {
  return v >= 65 ? "var(--good)" : v < 40 ? "var(--critical)" : "var(--warning)";
}

function playerRow(p) {
  const open = state.open.has(p.slot);
  const [cls, label] = VERDICT[p.verdict] || ["neutral", p.verdict_label];
  return `<div class="prow${open ? " open" : ""}" id="p-${p.slot}" data-slot="${p.slot}" tabindex="0" role="button" aria-expanded="${open}">
      <img class="portrait" src="${esc(p.hero_img)}" alt="" loading="lazy">
      <div class="pname"><div class="hero">${esc(p.hero)}${p.is_mvp ? '<span class="mvp-tag">MVP</span>' : ""}</div>
        <div class="sub">${esc(p.name)} · ${esc(p.pos_label)}${p.rank ? " · " + esc(p.rank) : ""}</div></div>
      <div class="kda">${p.kills} / <span class="d">${p.deaths}</span> / ${p.assists}<small>У / С / П</small></div>
      <div class="nw">${num(p.net_worth)}<small>нетворс</small></div>
      <div class="meter-cell"><div class="meter-row"><div class="meter">
          <div class="fill" style="width:${p.score}%;background:${meterColor(p.score)}"></div>
          <div class="tick" style="left:calc(${p.team_median}% - 1px)" title="Медиана команды: ${p.team_median}"></div></div>
        <span class="num">${p.score}</span></div></div>
      <div class="verdict" title="${esc(verdictWhy(p))}"><span class="pill ${cls}">${label}</span><span class="conf">${esc(p.confidence)}</span></div>
      <svg class="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>
    </div>
    ${open ? playerDetails(p) : ""}`;
}

function playerDetails(p) {
  const tab = state.tab[p.slot] || "score";
  const tabs = [["score", "Вклад"], ["items", "Закуп и ответ на пик"], ["skills", "Прокачка"]];
  const body = tab === "items" ? itemsBlock(p) + countersBlock(p) : tab === "skills" ? skillsBlock(p) : scoreBlock(p);
  return `<div class="pdetails">
    <div class="seg" data-ptab="${p.slot}">${tabs.map(([k, t]) => `<button data-v="${k}" class="${tab === k ? "active" : ""}">${t}</button>`).join("")}</div>
    ${body}</div>`;
}

function compColor(v) {
  return v >= 0.6 ? "var(--good)" : v <= 0.35 ? "var(--critical)" : "var(--warning)";
}

function scoreBlock(p) {
  const comps = [...p.components].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)).map((c) => `
    <div class="comp"><div class="top"><span>${esc(c.label)}</span><span class="muted">${Math.round(c.value * 100)}</span></div>
      <div class="cbar"><div style="width:${Math.round(c.value * 100)}%;background:${compColor(c.value)}"></div></div>
      <div class="ctext">${esc(c.text)}</div></div>`).join("");
  const reasons = p.reasons.length ? p.reasons.map((e) => {
    const [cls, label] = SEV[e.severity];
    return `<div class="reason"><span class="time">${e.time_fmt}</span><span class="pill ${cls}">${label}</span><span>${esc(e.text)}</span></div>`;
  }).join("") : '<div class="muted">Отдельных эпизодов нет — оценка сложилась из цифр слева.</div>';
  const lane = p.lane ? `<div class="fact-line">Линия против <b>${esc(p.lane_opponent)}</b> к 10:00: добивания ${p.lane.lh}/${p.lane.dn ?? 0} против ${p.lane.opp_lh}/${p.lane.opp_dn ?? 0},
    опыт ${p.lane.xp_diff >= 0 ? "+" : ""}${num(p.lane.xp_diff)}${p.lane.gold_diff != null ? `, золото ${p.lane.gold_diff >= 0 ? "+" : ""}${num(p.lane.gold_diff)}` : ""}, смертей ${p.lane.deaths}, убийств ${p.lane.kills}</div>` : "";
  const fights = p.fights ? `<div class="fact-line">Драки после 10:00: участвовал в ${p.fights.part} из ${p.fights.total}</div>` : "";
  return `<div class="cols">
    <div><div class="h3">Из чего сложился вклад</div>${comps}</div>
    <div><div class="h3">Почему «${esc(p.verdict_label)}»</div><div class="fact-line">${esc(verdictWhy(p))}</div>${reasons}
      <div class="h3" style="margin-top:16px">Стадии</div>${lane}${fights}
      <div class="fact-line">Мёртв ${p.dead_fmt} (${p.dead_pct}% матча) · участие в убийствах ${p.kp}% · ${p.nw_share}% нетворса команды · ${p.dmg_share}% урона команды</div></div>
  </div>`;
}

function itemTile(it, cls, top, bottom) {
  return `<div class="item ${cls}" title="${esc(it.name)}"><img src="${esc(it.img)}" alt="" loading="lazy">
    <div class="t">${esc(top)}</div><div class="pro">${esc(bottom)}</div></div>`;
}

function itemsBlock(p) {
  const it = p.items;
  const basis = it.basis === "pos" ? `на позиции ${p.pos}` : "на герое (на этой позиции мало игр)";
  let head;
  if (it.turbo) {
    head = it.available
      ? `<p class="muted">Это турбо: сравнение с ${it.samples} турбо-играми на ${esc(p.hero)} на вашем ранге (похожей длины) — что собирают.
          Тайминги «≈» — оценка: тайминг про × ${it.pace} (во столько раз быстрее копится золото в турбо).
          ${it.score != null ? `Оценка закупа: <b>${Math.round(it.score * 100)}/100</b>.` : ""}</p>`
      : `<p class="muted">Турбо-игр на ${esc(p.hero)} на вашем ранге мало (${it.samples}) — сравнение было бы шумом.</p>`;
  } else if (!it.samples) head = `<p class="muted">Свежих разобранных про-матчей на ${esc(p.hero)} не нашлось — сравнить не с чем.</p>`;
  else if (!it.available) head = `<p class="muted">Про-матчей мало (${it.samples}) — сравнение было бы шумом.</p>`;
  else head = `<p class="muted">Сравнение с ${it.samples} свежими матчами лиг ${basis}. Под иконкой — время покупки и медиана про.
    ${it.score != null ? `Оценка закупа: <b>${Math.round(it.score * 100)}/100</b>.` : ""}</p>`;
  const ref = it.turbo ? "≈" : "про";
  const timeline = it.timeline.length ? it.timeline.map((e) => itemTile(e, e.status, e.time_fmt,
    e.pro_median_fmt ? `${ref} ${e.pro_median_fmt}` : e.pro_alt ? `про: ${e.pro_alt}` : it.turbo && e.status === "offmeta" ? "турбо так не берут" : ITEM_STATUS[e.status])).join("")
    : '<span class="muted">Ключевых предметов не куплено.</span>';
  const missing = it.missing.map((e) => itemTile(e, "missing", "не собрал", `${ref} ${e.median_fmt} · ${e.share}%`)).join("");
  const core = it.core.length ? `<div class="h3" style="margin-top:18px">${it.turbo ? "Что собирают турбо-игроки (≥40% игр), с оценкой тайминга" : "Что собирают про (≥40% игр), по медиане тайминга"}</div><div class="timeline">${it.core.slice(0, 8).map((c) =>
    itemTile(c, c.bought_fmt ? "" : "missing", c.median_fmt, `${c.share}% · ${c.bought_fmt ? "у него " + c.bought_fmt : "нет"}`)).join("")}</div>` : "";
  const pop = it.popularity.length ? `<div class="h3">Популярность по стадиям (про-матчи)</div>${it.popularity.map((ph) =>
    `<div class="phase"><div class="label">${esc(ph.phase)}</div><div class="icons-row">${ph.items.map((x) => `<img src="${esc(x.img)}" title="${esc(x.name)} — ${x.count}" alt="">`).join("")}</div></div>`).join("")}` : "";
  const pros = it.pro_examples.length ? `<div class="h3">Про-матчи в выборке</div>${it.pro_examples.map((m) =>
    `<div class="fact-line"><a href="https://www.opendota.com/matches/${m.match_id}" target="_blank" rel="noopener">${m.match_id}</a> — ${esc(m.name || "игрок")}, поз. ${m.pos ?? "?"}, ${m.win ? "победа" : "поражение"}${m.league ? " · " + esc(m.league) : ""}</div>`).join("")}` : "";
  const who = it.turbo ? "турбо-игроки" : "про";
  return `<div class="h3">${it.turbo ? "Закуп против турбо-игроков" : "Закуп против про"}</div>${head}
    <div class="legend-items"><span><i style="background:var(--good)"></i>в тайминг</span><span><i style="background:var(--info)"></i>${it.turbo ? "раньше оценки" : "раньше про"}</span>
      <span><i style="background:var(--critical)"></i>${it.turbo ? "позже оценки" : "позже про"}</span><span><i style="background:var(--violet)"></i>${who} так не берут</span></div>
    <div class="timeline">${timeline}${missing}</div>${core}
    <div class="cols" style="margin-top:18px"><div>${pop}</div><div>${pros}</div></div>`;
}

function countersBlock(p) {
  const list = p.counters || [];
  if (!list.length) return "";
  return `<div class="h3" style="margin-top:22px">Ответ на пик врага</div>
    <p class="muted">Против сильных сторон вражеского пика обычно покупают конкретные предметы. Это эвристики, а не правило.</p>
    ${list.map((x) => `<div class="counter-row">
      <div><b>${esc(x.label)}</b><div class="muted small">${esc(x.enemies.join(", "))}</div></div>
      <div class="icons-row">${x.wanted.map((w) => `<img src="${esc(w.img)}" title="${esc(w.name)}" alt="">`).join("")}</div>
      <div>${x.have ? `<span class="pill good">${esc(x.have.name)} · ${x.have.time_fmt}</span>` : '<span class="pill critical">нет ответа</span>'}</div>
    </div>`).join("")}`;
}

function skillsBlock(p) {
  const s = p.skills || {};
  if (!s.build || !s.build.length) return '<p class="muted">Нет данных о прокачке.</p>';
  const ult = new Set(s.ultimates || []);
  const build = s.build.slice(0, 22).map((b) => {
    const talent = b.key.startsWith("special_bonus");
    return `<div class="skill${ult.has(b.key) ? " ult" : ""}${talent ? " talent" : ""}" title="${b.level}: ${esc(b.name)}">
      ${b.img && !talent ? `<img src="${esc(b.img)}" alt="">` : '<span class="tal">Т</span>'}<span class="lvl">${b.level}</span></div>`;
  }).join("");
  let cmp;
  const who = s.ref || "про";
  if (!s.available) cmp = `<p class="muted">Матчей с прокачкой мало (${s.samples || 0}) — сравнивать не с чем.</p>`;
  else {
    const basis = s.basis === "pos" ? "на этой позиции" : "на герое";
    const prio = s.priority && s.pro_priority ? `<div class="fact-line">Первым максил <b>${esc(s.priority.name)}</b>${s.priority_match ? ` — как и ${who}` :
      `, ${who} ${basis} — <b>${esc(s.pro_priority.name)}</b> (${s.pro_priority_share}%)`}</div>` : "";
    const ultl = (s.ult_late || []).map((u) => `<div class="reason"><span class="pill warning">Спорно</span>${u.rank}-й уровень ульта: у ${who} ${u.typical}-м очком, здесь ${u.taken ? u.taken + "-м" : "не взят"}</div>`).join("");
    const tal = (s.talents || []).length ? `<div class="h3" style="margin-top:14px">Таланты</div><table class="tbl"><thead><tr><th>Ур.</th><th>Взял</th><th>Чаще всего у ${who} (${s.samples} игр)</th></tr></thead><tbody>${s.talents.map((t) =>
      `<tr class="${t.match === false ? "diff" : ""}"><td>${t.level}</td><td>${t.mine ? esc(t.mine.name) : '<span class="muted">—</span>'}</td><td>${esc(t.pro.name)} <span class="muted">${t.pro_share}%</span></td></tr>`).join("")}</tbody></table>` : "";
    cmp = prio + ultl + tal;
  }
  return `<div class="h3">${who === "про" ? "Прокачка против про" : "Прокачка против турбо-игроков"}</div>
    <p class="muted small">Рамка золотом — ульт, синим — талант. Число — номер очка прокачки.</p>
    <div class="skills">${build}</div>${cmp}`;
}

// ---------- эпизоды ----------

function episodesPanel(r) {
  const f = state.epFilter;
  const list = r.episodes.filter((e) => f === "all" || (f === "bad" ? ["bad", "disputed"].includes(e.severity) : e.severity === "good"));
  const counts = { all: r.episodes.length, bad: r.episodes.filter((e) => ["bad", "disputed"].includes(e.severity)).length,
    good: r.episodes.filter((e) => e.severity === "good").length };
  const byStage = ["lane", "mid", "final"].map((st) => {
    const es = list.filter((e) => e.stage === st);
    if (!es.length) return "";
    return `<div class="stage-title">${STAGES[st]}</div>` + es.map((e) => {
      const p = e.slot != null ? heroOf(e.slot) : null;
      const [cls, label] = SEV[e.severity];
      return `<div class="ep">
        <div class="time">${e.time_fmt}${e.end_fmt ? `<small>до ${e.end_fmt}</small>` : ""}</div>
        ${p ? `<img class="avatar ${p.team}" src="${esc(p.hero_img)}" alt="" title="${esc(p.hero)}">` : '<div class="avatar">⚑</div>'}
        <div><div class="head"><span class="pill ${cls}">${label}</span>${esc(e.title)}</div>
          <div class="text">${esc(e.text)}</div>
          <div class="rule">${esc(e.rule)}${r.map ? ` · <a href="#" class="seek" data-t="${e.time}" data-slot="${e.slot ?? ""}">показать на карте</a>` : ""}</div></div>
      </div>`;
    }).join("");
  }).join("");
  return `<section class="panel" id="sec-episodes">
    <div class="panel-head"><div><h2>Эпизоды</h2><p class="sub">Моменты матча с таймкодами: факты из реплея и правила поверх них. «Спорно» — повод посмотреть, а не приговор.</p></div>
      <div class="seg" data-ep>
        <button data-v="all" class="${f === "all" ? "active" : ""}">Все · ${counts.all}</button>
        <button data-v="bad" class="${f === "bad" ? "active" : ""}">Спорное и плохое · ${counts.bad}</button>
        <button data-v="good" class="${f === "good" ? "active" : ""}">Хорошее · ${counts.good}</button></div></div>
    ${byStage || '<p class="muted">Нет эпизодов в этом фильтре.</p>'}</section>`;
}

// ---------- поряда, строения, чат ----------

function conductPanel(r) {
  if (!r.replay) return "";
  if (!r.replay.available) {
    return `<section class="panel" id="sec-conduct"><div class="panel-head"><div><h2>Поряда</h2>
      <p class="sub">Свой разбор реплея не сделан: ${esc(r.replay.reason || "нет данных")}. Без него не видно AFK, открытий таблицы и порядочности.</p></div></div></section>`;
  }
  const row = (p) => {
    const c = p.conduct || {};
    const signals = [];
    for (const w of c.afk || []) signals.push(`<span class="sig bad">AFK ${w.duration_fmt} с ${w.start_fmt}${w.stood_still ? ", стоял на месте" : ""}</span>`);
    if (c.toxic && c.toxic.length) signals.push(`<span class="sig bad" title="${esc(c.toxic.map((t) => t.time_fmt + " " + t.text).join("\n"))}">Токсичный чат · ${c.toxic.length}</span>`);
    const sb = c.scoreboard;
    if (sb && sb.deaths_with_tab) signals.push(`<span class="sig">Таблица после смерти · ${sb.deaths_with_tab} из ${sb.deaths}</span>`);
    return `<tr><td><div style="display:flex;gap:10px;align-items:center"><img src="${esc(p.hero_img)}" alt="" style="width:48px;height:27px;object-fit:cover;border-radius:6px">
      <div><b>${esc(p.name)}</b><div class="muted small">${esc(p.hero)}</div></div></div></td>
      <td>${esc(c.behavior ?? "—")}</td><td>${esc(c.comm ?? "—")}</td>
      <td>${signals.join(" ") || '<span class="sig ok">чисто</span>'}</td></tr>`;
  };
  const team = (t) => `<tr class="team-row"><td colspan="4" class="team-${t}">${TEAM[t]}</td></tr>` + r.players.filter((p) => p.team === t).map(row).join("");
  return `<section class="panel" id="sec-conduct">
    <div class="panel-head"><div><h2>Поряда</h2>
      <p class="sub">Порядочность и вежливость — полосы шкалы 0–12 000 из «Отчёта о порядочности» клиента на момент матча: реплей хранит уровень, а не точные очки.
        Репорты за этот матч Valve в реплей не пишет — ниже сигналы из игры. «Таблица после смерти» — после скольких смертей игрок открывал панель статистики (наш сигнал).</p></div></div>
    <div style="overflow-x:auto"><table class="tbl"><thead><tr><th>Игрок</th><th>Порядочность</th><th>Вежливость</th><th>Сигналы из игры</th></tr></thead>
      <tbody>${team("radiant")}${team("dire")}</tbody></table></div></section>`;
}

function objectivesPanel(r) {
  return `<section class="panel"><div class="panel-head"><h2>Строения и объекты</h2></div><div class="feed">${r.objectives.map((o) =>
    `<div class="feed-row ${o.team}"><span class="t">${o.time_fmt}</span><span class="who">${esc(o.text)}</span></div>`).join("") || '<p class="muted">Нет данных.</p>'}</div></section>`;
}

function chatPanel(r) {
  const f = state.chatFilter;
  const channel = (c) => c.channel || "all";
  const counts = { all: r.chat.length, everyone: r.chat.filter((c) => channel(c) === "all").length,
    allies: r.chat.filter((c) => channel(c) === "allies").length };
  const list = r.chat.filter((c) => f === "all" || (f === "allies" ? channel(c) === "allies" : channel(c) === "all"));
  const row = (c) => {
    const ally = channel(c) === "allies";
    const tag = ally ? `<span class="pill ${c.team || "neutral"}">союзникам</span>` : '<span class="pill neutral">всем</span>';
    return `<div class="feed-row ${c.team || ""}"><span class="t">${c.time_fmt}</span>
      <span>${tag} <span class="who">${esc(c.name)}</span>${c.hero ? ` <span class="muted">(${esc(c.hero)})</span>` : ""}
      — ${c.kind === "wheel" ? '<span class="muted">фраза:</span> ' : ""}${esc(c.text)}</span></div>`;
  };
  return `<section class="panel" id="sec-chat"><div class="panel-head"><div><h2>Чат</h2>
    <p class="sub">Фразы из колеса чата видны все — и всем, и союзникам. Текстовые сообщения — только из общего чата:
      то, что пишут союзникам вручную, Valve в реплей не записывает (реплей пишется глазами зрителя), поэтому этого не покажет ни один сайт.</p></div>
    <div class="seg" data-chat>
      <button data-v="all" class="${f === "all" ? "active" : ""}">Всё · ${counts.all}</button>
      <button data-v="everyone" class="${f === "everyone" ? "active" : ""}">Всем · ${counts.everyone}</button>
      <button data-v="allies" class="${f === "allies" ? "active" : ""}">Союзникам · ${counts.allies}</button></div></div>
    <div class="feed">${list.map(row).join("") || '<p class="muted">Пусто.</p>'}</div></section>`;
}

function notesPanel(r) {
  return `<section class="panel"><div class="panel-head"><h2>Чего разбор не знает</h2></div><ul class="notes">${r.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></section>`;
}

// ---------- события ----------

function toggleRow(slot) {
  state.open.has(slot) ? state.open.delete(slot) : state.open.add(slot);
  render();
  document.getElementById(`p-${slot}`)?.scrollIntoView({ block: "nearest" });
}

function bind() {
  document.querySelectorAll(".prow").forEach((row) => {
    const slot = Number(row.dataset.slot);
    row.addEventListener("click", () => toggleRow(slot));
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleRow(slot); } });
  });
  document.querySelectorAll("[data-ptab] button").forEach((b) => b.addEventListener("click", () => {
    state.tab[b.parentElement.dataset.ptab] = b.dataset.v;
    render();
  }));
  document.querySelectorAll("[data-ep] button").forEach((b) => b.addEventListener("click", () => {
    state.epFilter = b.dataset.v;
    render();
  }));
  document.querySelectorAll("[data-chat] button").forEach((b) => b.addEventListener("click", () => {
    state.chatFilter = b.dataset.v;
    render();
  }));
  document.querySelectorAll("[data-open]").forEach((a) => a.addEventListener("click", () => {
    state.open.add(Number(a.dataset.open));
    render();
    setTimeout(() => document.getElementById(`p-${a.dataset.open}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
  }));
  const refresh = $("#refresh");
  if (refresh) refresh.addEventListener("click", (e) => { e.preventDefault(); load(state.report.match_id, true); });
  document.querySelectorAll("a.seek").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    RuinerMap.seek(Number(a.dataset.t) - 5, a.dataset.slot === "" ? null : a.dataset.slot);
  }));
  MatchChart.mount(state.report, rerenderChart);
  RuinerMap.mount(state.report);
}

route();
