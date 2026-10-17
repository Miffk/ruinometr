"use strict";

// Карта матча: схема линий и реки, строения, варды, герои, смерти, следы и проигрывание по времени.
const RuinerMap = (() => {
  const SIZE = 1000;
  const OBS_VISION = 1600; // радиус обзора обсервера в единицах карты
  const RECENT_DEATH = 20; // столько секунд смерть подсвечивается ярко
  const TRAIL = 60; // длина следа героя в секундах

  const st = { t: 0, playing: false, speed: 30, wards: true, deaths: "recent", trails: new Set(), raf: null, last: null };
  let report = null;
  let players = {};

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (s) => { const n = Math.round(s), a = Math.abs(n); return `${n < 0 ? "-" : ""}${Math.floor(a / 60)}:${String(a % 60).padStart(2, "0")}`; };

  function proj(x, y) {
    const [lo, hi] = report.map.bounds;
    return [((x - lo) / (hi - lo)) * SIZE, SIZE - ((y - lo) / (hi - lo)) * SIZE];
  }
  const scale = (d) => (d / (report.map.bounds[1] - report.map.bounds[0])) * SIZE;

  // Позиция героя на момент t: последняя точка трека не позже t.
  function at(track, t) {
    let lo = 0, hi = track.length - 1, best = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (track[mid][0] <= t) { best = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return best;
  }

  function lanePath(buildings, team, lane) {
    return buildings.filter((b) => b.team === team && b.lane === lane && b.kind === "tower");
  }

  function background() {
    const m = report.map;
    const fort = (team) => m.buildings.find((b) => b.kind === "fort" && b.team === team);
    const fr = fort("radiant"), fd = fort("dire");
    const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
    const roads = [];
    if (fr && fd) {
      for (const lane of ["top", "mid", "bot"]) {
        const rad = lanePath(m.buildings, "radiant", lane).sort((a, b) => dist(a, fr) - dist(b, fr));
        const dire = lanePath(m.buildings, "dire", lane).sort((a, b) => dist(b, fd) - dist(a, fd));
        const pts = [fr, ...rad];
        if (lane !== "mid" && rad.length && dire.length) {
          // Угол линии: верх — левый верхний, низ — правый нижний.
          const all = [...rad, ...dire];
          const corner = lane === "top"
            ? { x: Math.min(...all.map((b) => b.x)), y: Math.max(...all.map((b) => b.y)) }
            : { x: Math.max(...all.map((b) => b.x)), y: Math.min(...all.map((b) => b.y)) };
          pts.push(corner);
        }
        pts.push(...dire, fd);
        roads.push(`<polyline points="${pts.map((b) => proj(b.x, b.y).map((v) => v.toFixed(0)).join(",")).join(" ")}" class="road"/>`);
      }
    }
    const river = [[-8200, 4300], [-3000, 2300], [0, 0], [3000, -2300], [8200, -4300]].map(([x, y]) => proj(x, y).join(",")).join(" ");
    const base = (b, cls) => {
      if (!b) return "";
      const [x, y] = proj(b.x, b.y);
      return `<circle cx="${x}" cy="${y}" r="${scale(4200)}" class="${cls}"/>`;
    };
    return `<rect width="${SIZE}" height="${SIZE}" class="ground"/>
      ${base(fr, "base-radiant")}${base(fd, "base-dire")}
      <polyline points="${river}" class="river"/>${roads.join("")}`;
  }

  function buildingsLayer(t) {
    return report.map.buildings.map((b) => {
      const [x, y] = proj(b.x, b.y);
      const dead = b.destroyed != null && b.destroyed <= t;
      const s = b.kind === "fort" ? 26 : b.kind === "tower" ? 14 : 10;
      const title = `${b.team === "radiant" ? "Свет" : "Тьма"} · ${b.label || b.kind}${b.destroyed != null ? " · снесено " + fmt(b.destroyed) : ""}`;
      return `<rect x="${x - s / 2}" y="${y - s / 2}" width="${s}" height="${s}" rx="2" class="bld ${b.team}${dead ? " dead" : ""}"><title>${esc(title)}</title></rect>`;
    }).join("");
  }

  function wardsLayer(t) {
    if (!st.wards) return "";
    return report.map.wards.filter((w) => w.start <= t && t < w.end).map((w) => {
      const [x, y] = proj(w.x, w.y);
      const title = `${w.kind === "observer" ? "Обсервер" : "Сентри"} · ${w.hero || "?"} · ${fmt(w.start)}–${fmt(w.end)}`;
      const vision = w.kind === "observer" ? `<circle cx="${x}" cy="${y}" r="${scale(OBS_VISION)}" class="vision ${w.team}"/>` : "";
      return `${vision}<circle cx="${x}" cy="${y}" r="5" class="ward ${w.kind} ${w.team}"><title>${esc(title)}</title></circle>`;
    }).join("");
  }

  function deathsLayer(t) {
    if (st.deaths === "none") return "";
    return report.map.deaths.filter((d) => d.time <= t && (st.deaths === "all" || t - d.time <= RECENT_DEATH)).map((d) => {
      const [x, y] = proj(d.x, d.y);
      const recent = t - d.time <= RECENT_DEATH;
      const title = `${d.time_fmt} — умер ${d.hero}${d.killer ? " (убил " + d.killer + ")" : ""}`;
      return `<g class="death ${d.team}${recent ? " recent" : ""}" transform="translate(${x},${y})"><title>${esc(title)}</title>
        <line x1="-7" y1="-7" x2="7" y2="7"/><line x1="-7" y1="7" x2="7" y2="-7"/></g>`;
    }).join("");
  }

  function heroesLayer(t) {
    const out = [];
    for (const [slot, track] of Object.entries(report.map.tracks)) {
      const p = players[slot];
      const i = at(track, t);
      if (!p || i < 0) continue;
      if (st.trails.has(slot)) {
        const pts = [];
        for (let j = i; j >= 0 && track[j][0] >= t - TRAIL; j--) if (track[j][3]) pts.push(proj(track[j][1], track[j][2]).join(","));
        if (pts.length > 1) out.push(`<polyline points="${pts.join(" ")}" class="trail ${p.team}"/>`);
      }
      const [, x, y, alive] = track[i];
      if (!alive) continue;
      const [sx, sy] = proj(x, y);
      out.push(`<g class="hero ${p.team}" transform="translate(${sx},${sy})" data-slot="${slot}"><title>${esc(p.hero + " · " + p.name)}</title>
        <circle r="15" class="ring"/>
        <image href="${esc(p.hero_img)}" x="-20" y="-13" width="40" height="26" clip-path="url(#hero-clip)" preserveAspectRatio="xMidYMid slice"/></g>`);
    }
    return out.join("");
  }

  function draw() {
    const g = document.getElementById("map-dyn");
    if (!g) return;
    const t = st.t;
    g.innerHTML = buildingsLayer(t) + wardsLayer(t) + deathsLayer(t) + heroesLayer(t);
    const slider = document.getElementById("map-time");
    if (slider && Number(slider.value) !== Math.round(t)) slider.value = Math.round(t);
    const label = document.getElementById("map-clock");
    if (label) label.textContent = fmt(t);
    const play = document.getElementById("map-play");
    if (play) play.textContent = st.playing ? "❚❚" : "▶";
  }

  function tick(now) {
    if (!st.playing) return;
    if (st.last != null) st.t = Math.min(report.map.duration, st.t + ((now - st.last) / 1000) * st.speed);
    st.last = now;
    if (st.t >= report.map.duration) st.playing = false;
    draw();
    if (st.playing) st.raf = requestAnimationFrame(tick);
  }

  function setPlaying(on) {
    st.playing = on;
    st.last = null;
    cancelAnimationFrame(st.raf);
    if (on) {
      if (st.t >= report.map.duration) st.t = 0;
      st.raf = requestAnimationFrame(tick);
    }
    draw();
  }

  function panel(r) {
    if (!r.map) return "";
    report = r;
    const legend = r.players.map((p) => `<button class="legend-hero ${p.team}${st.trails.has(String(p.slot)) ? " active" : ""}" data-slot="${p.slot}" title="Показать след за ${TRAIL} с">
      <img src="${esc(p.hero_img)}" alt="">${esc(p.hero)}</button>`).join("");
    return `<section class="panel map-panel" id="map-panel">
      <div class="panel-head"><div><h2>Карта матча</h2>
        <p class="sub">Позиции героев, варды, постройки и смерти по координатам из реплея. Запустите проигрывание или перетащите ползунок.
          Схема, а не точная карта: дороги проведены через башни, река — условно.</p></div></div>
      <div class="map-wrap">
        <svg viewBox="0 0 ${SIZE} ${SIZE}" class="map-svg">
          <defs><clipPath id="hero-clip"><circle r="13"/></clipPath></defs>
          ${background()}<g id="map-dyn"></g>
        </svg>
        <div class="map-side">
          <div class="map-controls">
            <button id="map-play" class="btn">▶</button>
            <span id="map-clock" class="map-clock">0:00</span>
            <select id="map-speed">${[10, 30, 60, 120].map((s) => `<option value="${s}"${s === st.speed ? " selected" : ""}>×${s}</option>`).join("")}</select>
          </div>
          <input id="map-time" type="range" min="-90" max="${r.map.duration}" step="1" value="${Math.round(st.t)}">
          <div class="map-toggles">
            <label><input type="checkbox" id="map-wards"${st.wards ? " checked" : ""}> варды</label>
            <select id="map-deaths">
              <option value="recent"${st.deaths === "recent" ? " selected" : ""}>смерти: последние ${RECENT_DEATH} с</option>
              <option value="all"${st.deaths === "all" ? " selected" : ""}>смерти: все до этого момента</option>
              <option value="none"${st.deaths === "none" ? " selected" : ""}>смерти: скрыть</option>
            </select>
          </div>
          <div class="map-key">
            <span><svg width="12" height="12"><rect x="1" y="1" width="10" height="10" rx="2" fill="var(--radiant)"/></svg>постройка Света</span>
            <span><svg width="12" height="12"><rect x="1" y="1" width="10" height="10" rx="2" fill="var(--dire)"/></svg>постройка Тьмы</span>
            <span><svg width="12" height="12"><rect x="1" y="1" width="10" height="10" rx="2" fill="none" stroke="var(--muted)" stroke-dasharray="3 2"/></svg>снесена</span>
            <span><svg width="12" height="12"><circle cx="6" cy="6" r="5" fill="#f0b43c"/></svg>обсервер</span>
            <span><svg width="12" height="12"><circle cx="6" cy="6" r="5" fill="#3987e5"/></svg>сентри</span>
            <span><svg width="12" height="12"><path d="M2 2 10 10M2 10 10 2" stroke="var(--text-2)" stroke-width="2.5" stroke-linecap="round"/></svg>смерть</span>
          </div>
          <div class="h3" style="margin:4px 0 0">След героя — нажмите</div>
          <div class="map-legend">${legend}</div>
        </div>
      </div></section>`;
  }

  function mount(r) {
    if (!r.map) return;
    report = r;
    players = Object.fromEntries(r.players.map((p) => [String(p.slot), p]));
    const on = (id, ev, fn) => { const el = document.getElementById(id); if (el) el.addEventListener(ev, fn); };
    on("map-play", "click", () => setPlaying(!st.playing));
    on("map-time", "input", (e) => { st.t = Number(e.target.value); setPlaying(false); });
    on("map-speed", "change", (e) => { st.speed = Number(e.target.value); });
    on("map-wards", "change", (e) => { st.wards = e.target.checked; draw(); });
    on("map-deaths", "change", (e) => { st.deaths = e.target.value; draw(); });
    document.querySelectorAll(".legend-hero").forEach((b) => b.addEventListener("click", () => {
      const s = b.dataset.slot;
      st.trails.has(s) ? st.trails.delete(s) : st.trails.add(s);
      b.classList.toggle("active", st.trails.has(s));
      draw();
    }));
    if (st.playing) setPlaying(true); else draw();
  }

  function seek(t, slot) {
    st.t = Math.max(-90, t);
    if (slot != null) st.trails.add(String(slot));
    setPlaying(false);
    document.querySelectorAll(".legend-hero").forEach((b) => b.classList.toggle("active", st.trails.has(b.dataset.slot)));
    const panelEl = document.getElementById("map-panel");
    if (panelEl) panelEl.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function reset() {
    setPlaying(false);
    Object.assign(st, { t: 0, trails: new Set() });
  }

  return { panel, mount, seek, reset };
})();
