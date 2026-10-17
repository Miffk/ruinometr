"use strict";

// График «Ход матча»: разница золота или опыта команд по минутам + дорожки событий под ним.
// Выше нуля — впереди Силы Света, ниже — Силы Тьмы. Под графиком на той же шкале времени —
// снесённые постройки и убийства каждой команды. Наведение показывает значения и события минуты.
const MatchChart = (() => {
  const st = { mode: "gold", minute: null };
  let report = null;
  let geom = null;
  let observer = null;

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtT = (s) => { const n = Math.round(s), a = Math.abs(n); return `${n < 0 ? "-" : ""}${Math.floor(a / 60)}:${String(a % 60).padStart(2, "0")}`; };
  const num = (n) => Math.round(n).toLocaleString("ru-RU");
  const signed = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + num(Math.abs(n));
  const short = (v) => {
    const a = Math.abs(v);
    const s = a >= 1000 ? `${(a / 1000).toLocaleString("ru-RU", { maximumFractionDigits: a >= 10000 ? 0 : 1 })}k` : String(Math.round(a));
    return v > 0 ? `+${s}` : v < 0 ? `−${s}` : "0";
  };
  const TEAM = { radiant: "Свет", dire: "Тьма" };
  const MODE = { gold: { title: "золота", noun: "Золото" }, xp: { title: "опыта", noun: "Опыт" } };
  const KIND_ICON = { tower: "башня", barracks: "барак", fort: "Трон", roshan: "Рошан" };

  const series = () => (st.mode === "gold" ? report.gold_adv : report.xp_adv) || [];

  // События: постройки (кто снёс) и Рошан (кто убил), убийства (чья команда убила).
  function events() {
    const ev = [];
    for (const o of report.objectives || []) {
      if (o.kind === "building") {
        const by = o.team === "radiant" ? "dire" : "radiant";
        const kind = o.label.startsWith("барак") ? "barracks" : o.label === "Трон" ? "fort" : "tower";
        ev.push({ time: o.time, lane: "build", team: by, kind, text: `${TEAM[by]} сносит: ${o.label}` });
      } else if (o.kind === "roshan") {
        ev.push({ time: o.time, lane: "build", team: o.team, kind: "roshan", text: `${TEAM[o.team]} убивает Рошана` });
      }
    }
    for (const d of report.deaths || []) {
      const by = d.team === "radiant" ? "dire" : "radiant";
      ev.push({ time: d.time, lane: "kill", team: by, kind: "kill", text: `${d.hero} погиб${d.killer ? ` (убил ${d.killer})` : ""}` });
    }
    return ev;
  }

  function stats(s) {
    let maxR = { v: 0, m: 0 }, maxD = { v: 0, m: 0 };
    s.forEach((v, m) => { if (v > maxR.v) maxR = { v, m }; if (-v > maxD.v) maxD = { v: -v, m }; });
    let lastFlip = null;
    for (let m = 1; m < s.length; m++) if (Math.sign(s[m]) !== Math.sign(s[m - 1]) && s[m] !== 0) lastFlip = m;
    const end = s[s.length - 1] || 0;
    const leader = end >= 0 ? "radiant" : "dire";
    const tile = (k, v, sub) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}${sub ? `<small>${sub}</small>` : ""}</div></div>`;
    return `<div class="chart-stats">
      ${tile(`Макс. преимущество Света`, maxR.v ? `<span class="team-radiant">${short(maxR.v)}</span>` : "—", maxR.v ? `на ${maxR.m}:00` : "не было")}
      ${tile(`Макс. преимущество Тьмы`, maxD.v ? `<span class="team-dire">${short(maxD.v)}</span>` : "—", maxD.v ? `на ${maxD.m}:00` : "не было")}
      ${tile("В конце матча", `<span class="team-${leader}">${short(Math.abs(end))}</span>`, `у ${leader === "radiant" ? "Света" : "Тьмы"}`)}
      ${tile("Лидер не менялся", lastFlip ? `с ${lastFlip}:00` : "весь матч", lastFlip ? "" : "")}
    </div>`;
  }

  function panel(r) {
    report = r;
    const s = series();
    if (s.length < 2) return "";
    const rows = s.map((v, m) => {
      const evs = events().filter((e) => Math.floor(e.time / 60) === m && e.lane === "build").map((e) => e.text);
      const kills = { radiant: 0, dire: 0 };
      events().filter((e) => e.lane === "kill" && Math.floor(e.time / 60) === m).forEach((e) => kills[e.team]++);
      return `<tr><td>${m}:00</td><td>${signed((r.gold_adv || [])[m] || 0)}</td><td>${signed((r.xp_adv || [])[m] || 0)}</td>
        <td>${kills.radiant}</td><td>${kills.dire}</td><td>${esc(evs.join("; "))}</td></tr>`;
    }).join("");
    return `<section class="panel" id="sec-flow">
      <div class="panel-head">
        <div><h2>Ход матча</h2>
          <p class="sub">Разница ${MODE[st.mode].title} между командами по минутам. Выше нуля — впереди Силы Света, ниже — Силы Тьмы.
            Под графиком на той же шкале — снесённые постройки и убийства. Наведите на график, чтобы увидеть минуту целиком.</p></div>
        <div class="seg" data-chart-mode>
          <button data-v="gold" class="${st.mode === "gold" ? "active" : ""}">Золото</button>
          <button data-v="xp" class="${st.mode === "xp" ? "active" : ""}">Опыт</button>
        </div>
      </div>
      ${stats(s)}
      <div class="chart-box" id="mc-box"><svg class="chart-svg" id="mc-svg" role="img" aria-label="График разницы ${MODE[st.mode].title} по минутам"></svg>
        <div class="tooltip" id="mc-tip"></div></div>
      <div class="chart-legend">
        <span class="li"><svg width="22" height="10"><line x1="1" y1="5" x2="21" y2="5" stroke="var(--radiant)" stroke-width="2.5"/></svg>Свет впереди</span>
        <span class="li"><svg width="22" height="10"><line x1="1" y1="5" x2="21" y2="5" stroke="var(--dire)" stroke-width="2.5"/></svg>Тьма впереди</span>
        <span class="li"><svg width="12" height="12"><rect x="2" y="2" width="8" height="8" rx="1.5" fill="var(--text-2)"/></svg>башня</span>
        <span class="li"><svg width="16" height="12"><rect x="1" y="3" width="14" height="6" rx="1.5" fill="var(--text-2)"/></svg>барак</span>
        <span class="li"><svg width="14" height="14"><rect x="3" y="3" width="8" height="8" transform="rotate(45 7 7)" fill="var(--text-2)"/></svg>Трон</span>
        <span class="li"><svg width="14" height="14"><circle cx="7" cy="7" r="4.5" fill="none" stroke="var(--text-2)" stroke-width="2"/></svg>Рошан</span>
        <span class="li"><svg width="8" height="14"><rect x="3" y="1" width="2.5" height="12" rx="1" fill="var(--text-2)"/></svg>убийство</span>
        <span class="muted">Цвет значка — команда, которая сделала событие.</span>
      </div>
      <details class="data-table"><summary>Таблица по минутам</summary><div class="scroll">
        <table class="tbl"><thead><tr><th>Минута</th><th>Золото (Свет − Тьма)</th><th>Опыт (Свет − Тьма)</th><th>Убийств Света</th><th>Убийств Тьмы</th><th>Постройки и Рошан</th></tr></thead>
        <tbody>${rows}</tbody></table></div></details>
    </section>`;
  }

  function niceStep(maxAbs) {
    for (const step of [500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000]) if (maxAbs / step <= 3) return step;
    return 100000;
  }

  function draw() {
    const box = document.getElementById("mc-box");
    const svg = document.getElementById("mc-svg");
    if (!box || !svg) return;
    const s = series();
    const W = Math.max(320, box.clientWidth);
    const narrow = W < 560;
    const L = narrow ? 40 : 52, R = narrow ? 12 : 20, T = 14, PH = narrow ? 180 : 230;
    const laneH = 26, laneGap = 18, lanes = [
      { key: "build", team: "radiant", label: "Свет: постройки и Рошан" },
      { key: "build", team: "dire", label: "Тьма: постройки и Рошан" },
      { key: "kill", team: "radiant", label: "Свет: убийства" },
      { key: "kill", team: "dire", label: "Тьма: убийства" },
    ];
    const laneTop = T + PH + 50;
    const H = laneTop + lanes.length * (laneH + laneGap) - laneGap + 6;
    const PW = W - L - R;
    const N = s.length - 1;
    const step = niceStep(Math.max(1, ...s.map(Math.abs)));
    const yMax = Math.max(step, Math.ceil(Math.max(...s.map(Math.abs)) / step) * step);
    const x = (m) => L + (m / N) * PW;
    const y = (v) => T + PH / 2 - (v / yMax) * (PH / 2);
    const y0 = y(0);
    geom = { L, R, T, PH, PW, N, W, H, x, y, laneTop, laneH, laneGap, lanes };

    const out = [];
    // сетка и ось Y
    for (let v = -yMax; v <= yMax; v += step) {
      out.push(`<line class="${v === 0 ? "zero" : "grid"}" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>`);
      out.push(`<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${short(v)}</text>`);
    }
    // ось X
    const xStep = N > 50 ? 10 : 5;
    for (let m = 0; m <= N; m += xStep) {
      out.push(`<line class="grid" x1="${x(m)}" x2="${x(m)}" y1="${T}" y2="${T + PH}"/>`);
      out.push(`<text x="${x(m)}" y="${T + PH + 18}" text-anchor="middle">${m}:00</text>`);
    }
    // подписи сторон
    out.push(`<text class="side-label" x="${L + 10}" y="${T + 14}">▲ Свет впереди</text>`);
    out.push(`<text class="side-label" x="${L + 10}" y="${T + PH - 8}">▼ Тьма впереди</text>`);
    // область и линия, раскрашенные по знаку
    const pts = s.map((v, m) => `${x(m).toFixed(1)},${y(v).toFixed(1)}`);
    const area = `M${x(0)},${y0} L${pts.join(" L")} L${x(N)},${y0} Z`;
    const line = `M${pts.join(" L")}`;
    out.push(`<defs>
      <clipPath id="mc-up"><rect x="0" y="0" width="${W}" height="${y0}"/></clipPath>
      <clipPath id="mc-down"><rect x="0" y="${y0}" width="${W}" height="${H}"/></clipPath></defs>`);
    out.push(`<path d="${area}" fill="var(--radiant-fill)" clip-path="url(#mc-up)"/>`);
    out.push(`<path d="${area}" fill="var(--dire-fill)" clip-path="url(#mc-down)"/>`);
    out.push(`<path d="${line}" fill="none" stroke="var(--radiant)" stroke-width="2.5" stroke-linejoin="round" clip-path="url(#mc-up)"/>`);
    out.push(`<path d="${line}" fill="none" stroke="var(--dire)" stroke-width="2.5" stroke-linejoin="round" clip-path="url(#mc-down)"/>`);
    // пики — подписываем выборочно: максимум каждой стороны
    let hi = 0, lo = 0;
    s.forEach((v, m) => { if (v > s[hi]) hi = m; if (v < s[lo]) lo = m; });
    const peak = (m, up) => {
      const v = s[m];
      if (Math.abs(v) < step / 2) return "";
      const anchor = m > N * 0.8 ? "end" : m < N * 0.15 ? "start" : "middle";
      return `<circle cx="${x(m)}" cy="${y(v)}" r="4" fill="var(--${up ? "radiant" : "dire"})" stroke="var(--surface)" stroke-width="2"/>
        <text class="peak-label" x="${x(m)}" y="${y(v) + (up ? -9 : 18)}" text-anchor="${anchor}">${short(v)} · ${m}:00</text>`;
    };
    out.push(peak(hi, true), peak(lo, false));

    // дорожки событий
    const ev = events();
    lanes.forEach((ln, i) => {
      const top = laneTop + i * (laneH + laneGap);
      const cy = top + laneH / 2 + 4;
      out.push(`<text class="lane-label" x="${L}" y="${top}">${ln.label}</text>`);
      out.push(`<rect class="lane-bg" x="${L}" y="${top + 5}" width="${PW}" height="${laneH - 2}" rx="6"/>`);
      const laneEvents = ev.filter((e) => e.lane === ln.key && e.team === ln.team);
      if (!laneEvents.length) out.push(`<text x="${L + 10}" y="${cy + 4}">нет событий</text>`);
      for (const e of laneEvents) {
        const ex = x(Math.min(N, e.time / 60));
        const c = `var(--${e.team})`;
        let mark;
        if (e.kind === "tower") mark = `<rect x="${ex - 4.5}" y="${cy - 4.5}" width="9" height="9" rx="1.5" fill="${c}" stroke="var(--surface)" stroke-width="1.5"/>`;
        else if (e.kind === "barracks") mark = `<rect x="${ex - 7}" y="${cy - 3.5}" width="14" height="7" rx="1.5" fill="${c}" stroke="var(--surface)" stroke-width="1.5"/>`;
        else if (e.kind === "fort") mark = `<rect x="${ex - 5.5}" y="${cy - 5.5}" width="11" height="11" transform="rotate(45 ${ex} ${cy})" fill="${c}" stroke="var(--surface)" stroke-width="1.5"/>`;
        else if (e.kind === "roshan") mark = `<circle cx="${ex}" cy="${cy}" r="5" fill="var(--surface)" stroke="${c}" stroke-width="2.5"/>`;
        else mark = `<rect x="${ex - 1.25}" y="${cy - 7}" width="2.5" height="14" rx="1" fill="${c}" opacity=".85"/>`;
        out.push(`<g class="ev">${mark}</g>`);
      }
    });

    // слой наведения
    out.push(`<line class="cross" id="mc-cross" x1="0" x2="0" y1="${T}" y2="${H - 4}" visibility="hidden"/>`);
    out.push(`<circle id="mc-dot" r="5" stroke="var(--surface)" stroke-width="2" visibility="hidden"/>`);
    out.push(`<rect id="mc-hit" x="${L}" y="${T}" width="${PW}" height="${H - T}" fill="transparent" tabindex="0"
      aria-label="Наведите или используйте стрелки, чтобы посмотреть минуту"/>`);

    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("width", W);
    svg.setAttribute("height", H);
    svg.innerHTML = out.join("");
    bindHover();
    if (st.minute != null) showMinute(st.minute);
  }

  function showMinute(m) {
    const g = geom, s = series();
    m = Math.max(0, Math.min(g.N, m));
    st.minute = m;
    const v = s[m] || 0, team = v >= 0 ? "radiant" : "dire";
    const cross = document.getElementById("mc-cross"), dot = document.getElementById("mc-dot"), tip = document.getElementById("mc-tip");
    if (!cross || !tip) return;
    const cx = g.x(m);
    cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", cx); dot.setAttribute("cy", g.y(v)); dot.setAttribute("fill", `var(--${team})`); dot.setAttribute("visibility", "visible");

    const other = st.mode === "gold" ? (report.xp_adv || [])[m] : (report.gold_adv || [])[m];
    const otherName = st.mode === "gold" ? "опыта" : "золота";
    const within = events().filter((e) => e.time >= m * 60 - 30 && e.time < m * 60 + 30);
    const kills = { radiant: 0, dire: 0 };
    within.filter((e) => e.lane === "kill").forEach((e) => kills[e.team]++);
    const builds = within.filter((e) => e.lane === "build");
    const lead = (val) => (val > 0 ? "у Света" : val < 0 ? "у Тьмы" : "поровну");
    tip.innerHTML = `<div class="t">${m}:00</div>
      <div class="row"><span class="key" style="background:var(--${team})"></span><span class="val">${short(Math.abs(v)).replace("+", "")}</span>
        <span class="muted">${MODE[st.mode].title} ${lead(v)}</span></div>
      ${other != null ? `<div class="row"><span class="key" style="background:var(--${other >= 0 ? "radiant" : "dire"})"></span><span>${short(Math.abs(other)).replace("+", "")}</span>
        <span class="muted">${otherName} ${lead(other)}</span></div>` : ""}
      ${kills.radiant || kills.dire ? `<div class="ev-row">Убийства за минуту: Свет ${kills.radiant}, Тьма ${kills.dire}</div>` : ""}
      ${builds.map((e) => `<div class="ev-row">${fmtT(e.time)} — ${esc(e.text)}</div>`).join("")}`;
    tip.classList.add("show");
    const box = document.getElementById("mc-box");
    const tw = tip.offsetWidth;
    const left = cx + 14 + tw > box.clientWidth ? cx - tw - 14 : cx + 14;
    tip.style.left = `${Math.max(0, left)}px`;
    tip.style.top = `${g.T + 8}px`;
  }

  function hide() {
    st.minute = null;
    for (const id of ["mc-cross", "mc-dot"]) document.getElementById(id)?.setAttribute("visibility", "hidden");
    document.getElementById("mc-tip")?.classList.remove("show");
  }

  function bindHover() {
    const hit = document.getElementById("mc-hit");
    if (!hit) return;
    const toMinute = (ev) => {
      const rect = document.getElementById("mc-svg").getBoundingClientRect();
      const px = ev.clientX - rect.left;
      return Math.round(((px - geom.L) / geom.PW) * geom.N);
    };
    hit.addEventListener("pointermove", (ev) => showMinute(toMinute(ev)));
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("focus", () => showMinute(st.minute ?? 0));
    hit.addEventListener("blur", hide);
    hit.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
        ev.preventDefault();
        showMinute((st.minute ?? 0) + (ev.key === "ArrowRight" ? 1 : -1));
      }
    });
  }

  function mount(r, rerender) {
    report = r;
    document.querySelectorAll("[data-chart-mode] button").forEach((b) => b.addEventListener("click", () => {
      st.mode = b.dataset.v;
      st.minute = null;
      rerender();
    }));
    draw();
    if (observer) observer.disconnect();
    const box = document.getElementById("mc-box");
    if (box && "ResizeObserver" in window) {
      let lastW = box.clientWidth;
      observer = new ResizeObserver(() => { if (box.clientWidth !== lastW) { lastW = box.clientWidth; draw(); } });
      observer.observe(box);
    }
  }

  return { panel, mount };
})();
