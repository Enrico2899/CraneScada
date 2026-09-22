"use strict";

// Metadati dei campi di CraneSnapshot (vedi plc_comm/db_mapping.py).
// chartSlot: assegnazione FISSA per campo del colore/serie nel grafico
// (1-8, dalla palette categoriale) — mai ricalcolata in base a quali
// variabili sono selezionate, cosi' un campo mantiene sempre lo stesso
// colore anche quando altre serie vengono aggiunte/rimosse.
const FIELD_GROUPS = [
  {
    name: "Missione",
    fields: [
      { key: "mission_id", label: "Mission ID", type: "mission_id", defaultOn: true },
      { key: "step_number", label: "Step", type: "int", defaultOn: true },
      { key: "operating_mode", label: "Modalità operativa", type: "int", defaultOn: true },
      { key: "task_type", label: "Tipo task", type: "int" },
    ],
  },
  {
    name: "Segnali",
    fields: [
      { key: "mission_active", label: "Mission active", type: "bool" },
      { key: "mission_pause", label: "Mission pause", type: "bool" },
      { key: "waiting_interaction", label: "In attesa interazione", type: "bool" },
      { key: "movement_detected", label: "Movimento rilevato", type: "bool" },
      { key: "pickup_active", label: "Pickup attivo", type: "bool" },
      { key: "deposit_active", label: "Deposit attivo", type: "bool" },
    ],
  },
  {
    name: "Posizione",
    fields: [
      { key: "pos_x", label: "Posizione X", type: "float", chartSlot: 1, defaultOn: true },
      { key: "pos_y", label: "Posizione Y", type: "float", chartSlot: 2, defaultOn: true },
      { key: "pos_z", label: "Posizione Z", type: "float", chartSlot: 3, defaultOn: true },
    ],
  },
  {
    name: "Peso",
    fields: [
      { key: "lifted_weight", label: "Peso sollevato", type: "float", chartSlot: 4 },
    ],
  },
  {
    name: "Target pickup",
    fields: [
      { key: "target_pickup_x", label: "Target pickup X", type: "float", chartSlot: 5 },
      { key: "target_pickup_y", label: "Target pickup Y", type: "float", chartSlot: 6 },
      { key: "target_pickup_z", label: "Target pickup Z", type: "float" },
    ],
  },
  {
    name: "Target deposit",
    fields: [
      { key: "target_deposit_x", label: "Target deposit X", type: "float", chartSlot: 7 },
      { key: "target_deposit_y", label: "Target deposit Y", type: "float", chartSlot: 8 },
      { key: "target_deposit_z", label: "Target deposit Z", type: "float" },
    ],
  },
  {
    name: "Laser pickup",
    fields: [
      { key: "laser_pickup_x", label: "Laser pickup X", type: "float" },
      { key: "laser_pickup_y", label: "Laser pickup Y", type: "float" },
      { key: "laser_pickup_z", label: "Laser pickup Z", type: "float" },
    ],
  },
  {
    name: "Laser deposit",
    fields: [
      { key: "laser_deposit_x", label: "Laser deposit X", type: "float" },
      { key: "laser_deposit_y", label: "Laser deposit Y", type: "float" },
      { key: "laser_deposit_z", label: "Laser deposit Z", type: "float" },
    ],
  },
  {
    name: "Stato PLC",
    fields: [
      { key: "cycle_counter", label: "Cycle counter", type: "int" },
      { key: "version_db", label: "Versione DB", type: "int" },
    ],
  },
];

const ALL_FIELDS = FIELD_GROUPS.flatMap((g) => g.fields);
const FIELDS_BY_KEY = Object.fromEntries(ALL_FIELDS.map((f) => [f.key, f]));

const STORAGE_KEY = "cranescada_selected_fields_v1";
const CHART_WINDOW_S = 30;

const state = {
  checked: new Set(),
  buffers: new Map(), // key -> [{t, v}, ...]
  chartStart: performance.now(),
  ws: null,
  redrawScheduled: false,
  hover: null, // {x: canvasX} while mouse is over the chart
};

function loadCheckedFields() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return new Set(JSON.parse(raw));
  } catch (e) {
    /* ignore, usa i default */
  }
  return new Set(ALL_FIELDS.filter((f) => f.defaultOn).map((f) => f.key));
}

function saveCheckedFields() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...state.checked]));
  } catch (e) {
    /* privato/quota piena: va bene, e' solo una comodita' */
  }
}

function seriesColor(slot) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--series-${slot}`).trim();
}

// ---------- Pannello selezione variabili ----------

function buildFieldPicker() {
  const container = document.getElementById("field-groups");
  container.innerHTML = "";

  for (const group of FIELD_GROUPS) {
    const groupEl = document.createElement("div");
    groupEl.className = "field-group";

    const heading = document.createElement("h3");
    heading.textContent = group.name;
    groupEl.appendChild(heading);

    for (const field of group.fields) {
      const row = document.createElement("label");
      row.className = "field-row" + (field.chartSlot ? " chartable" : "");
      row.dataset.key = field.key;

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = state.checked.has(field.key);
      checkbox.addEventListener("change", () => onFieldToggle(field, checkbox.checked));

      const swatch = document.createElement("span");
      swatch.className = "field-swatch";
      if (field.chartSlot) swatch.style.background = seriesColor(field.chartSlot);

      const text = document.createElement("span");
      text.textContent = field.label;

      row.appendChild(checkbox);
      row.appendChild(swatch);
      row.appendChild(text);
      row.classList.toggle("checked", checkbox.checked);
      groupEl.appendChild(row);
    }
    container.appendChild(groupEl);
  }
}

function onFieldToggle(field, isChecked) {
  if (isChecked) {
    state.checked.add(field.key);
    if (field.chartSlot) state.buffers.set(field.key, []);
  } else {
    state.checked.delete(field.key);
    state.buffers.delete(field.key);
  }
  saveCheckedFields();
  const row = document.querySelector(`.field-row[data-key="${field.key}"]`);
  if (row) row.classList.toggle("checked", isChecked);
  rebuildTiles();
  rebuildLegend();
  scheduleRedraw();
}

// ---------- Tile con i valori live ----------

function rebuildTiles() {
  const container = document.getElementById("tiles");
  container.innerHTML = "";

  const visibleFields = ALL_FIELDS.filter((f) => state.checked.has(f.key));
  if (visibleFields.length === 0) {
    const empty = document.createElement("div");
    empty.className = "tile-empty";
    empty.textContent = "Nessuna variabile selezionata — spuntane qualcuna nel pannello a sinistra.";
    container.appendChild(empty);
    return;
  }

  for (const field of visibleFields) {
    const tile = document.createElement("div");
    tile.className = "tile" + (field.chartSlot ? " chartable" : "");
    tile.id = `tile-${field.key}`;
    if (field.chartSlot) tile.style.borderTopColor = seriesColor(field.chartSlot);

    const label = document.createElement("div");
    label.className = "tile-label";
    label.textContent = field.label;

    const value = document.createElement("div");
    value.className = "tile-value";
    value.id = `tile-value-${field.key}`;
    value.textContent = "—";

    tile.appendChild(label);
    tile.appendChild(value);
    container.appendChild(tile);
  }
}

function formatValue(field, raw) {
  if (raw === undefined || raw === null) return "—";
  switch (field.type) {
    case "bool":
      return raw ? "ON" : "OFF";
    case "mission_id":
      return raw === 0 ? "-" : String(raw);
    case "float":
      return Number(raw).toFixed(2);
    default:
      return String(raw);
  }
}

function updateTiles(snapshot) {
  for (const field of ALL_FIELDS) {
    if (!state.checked.has(field.key)) continue;
    const el = document.getElementById(`tile-value-${field.key}`);
    if (!el) continue;
    const raw = snapshot[field.key];
    el.textContent = formatValue(field, raw);
    if (field.type === "bool") {
      el.classList.toggle("bool-on", !!raw);
      el.classList.toggle("bool-off", !raw);
    }
  }
}

// ---------- Grafico live (canvas) ----------

function rebuildLegend() {
  const legend = document.getElementById("chart-legend");
  legend.innerHTML = "";
  const active = ALL_FIELDS.filter((f) => f.chartSlot && state.checked.has(f.key));
  for (const field of active) {
    const item = document.createElement("span");
    item.className = "legend-item";
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.background = seriesColor(field.chartSlot);
    const label = document.createElement("span");
    label.textContent = field.label;
    item.appendChild(swatch);
    item.appendChild(label);
    legend.appendChild(item);
  }
}

function pushChartPoint(snapshot) {
  const t = (performance.now() - state.chartStart) / 1000;
  const cutoff = t - CHART_WINDOW_S;
  for (const field of ALL_FIELDS) {
    if (!field.chartSlot || !state.checked.has(field.key)) continue;
    const buf = state.buffers.get(field.key) || [];
    buf.push({ t, v: Number(snapshot[field.key]) });
    while (buf.length > 1 && buf[0].t < cutoff) buf.shift();
    state.buffers.set(field.key, buf);
  }
}

function scheduleRedraw() {
  if (state.redrawScheduled) return;
  state.redrawScheduled = true;
  requestAnimationFrame(() => {
    state.redrawScheduled = false;
    drawChart();
  });
}

function drawChart() {
  const canvas = document.getElementById("chart");
  const ctx = canvas.getContext("2d");
  const cssWidth = canvas.clientWidth || 900;
  const cssHeight = canvas.clientHeight || 360;
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== cssWidth * dpr || canvas.height !== cssHeight * dpr) {
    canvas.width = cssWidth * dpr;
    canvas.height = cssHeight * dpr;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  const style = getComputedStyle(document.documentElement);
  const gridColor = style.getPropertyValue("--gridline").trim();
  const baselineColor = style.getPropertyValue("--baseline").trim();
  const mutedColor = style.getPropertyValue("--text-muted").trim();

  const activeSeries = ALL_FIELDS
    .filter((f) => f.chartSlot && state.checked.has(f.key))
    .map((f) => ({ field: f, points: state.buffers.get(f.key) || [] }))
    .filter((s) => s.points.length > 0);

  const margin = { top: 10, right: 12, bottom: 22, left: 48 };
  const plotW = Math.max(1, cssWidth - margin.left - margin.right);
  const plotH = Math.max(1, cssHeight - margin.top - margin.bottom);

  const nowT = (performance.now() - state.chartStart) / 1000;
  const xMin = Math.max(0, nowT - CHART_WINDOW_S);
  const xMax = Math.max(nowT, xMin + 1);

  if (activeSeries.length === 0) {
    ctx.fillStyle = mutedColor;
    ctx.font = "13px system-ui, sans-serif";
    ctx.fillText("Seleziona almeno una variabile con grafico per vedere le linee.", margin.left, margin.top + plotH / 2);
    return;
  }

  let yMin = Infinity;
  let yMax = -Infinity;
  for (const s of activeSeries) {
    for (const p of s.points) {
      if (p.v < yMin) yMin = p.v;
      if (p.v > yMax) yMax = p.v;
    }
  }
  if (!isFinite(yMin) || !isFinite(yMax)) { yMin = 0; yMax = 1; }
  if (yMin === yMax) { yMin -= 1; yMax += 1; }
  const yPad = (yMax - yMin) * 0.08;
  yMin -= yPad;
  yMax += yPad;

  const xToPx = (t) => margin.left + ((t - xMin) / (xMax - xMin)) * plotW;
  const yToPx = (v) => margin.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  // Griglia orizzontale + etichette asse Y
  ctx.strokeStyle = gridColor;
  ctx.lineWidth = 1;
  ctx.fillStyle = mutedColor;
  ctx.font = "11px system-ui, sans-serif";
  ctx.textBaseline = "middle";
  const yTicks = 5;
  for (let i = 0; i <= yTicks; i++) {
    const v = yMin + ((yMax - yMin) * i) / yTicks;
    const py = yToPx(v);
    ctx.beginPath();
    ctx.moveTo(margin.left, py);
    ctx.lineTo(margin.left + plotW, py);
    ctx.stroke();
    ctx.fillText(v.toFixed(1), 4, py);
  }

  // Asse X (baseline) + etichette tempo
  ctx.strokeStyle = baselineColor;
  ctx.beginPath();
  ctx.moveTo(margin.left, margin.top + plotH);
  ctx.lineTo(margin.left + plotW, margin.top + plotH);
  ctx.stroke();
  ctx.textBaseline = "top";
  ctx.textAlign = "center";
  const xTicks = 6;
  for (let i = 0; i <= xTicks; i++) {
    const t = xMin + ((xMax - xMin) * i) / xTicks;
    const px = xToPx(t);
    ctx.fillText(`-${Math.round(xMax - t)}s`, px, margin.top + plotH + 5);
  }
  ctx.textAlign = "left";

  // Linee delle serie
  for (const s of activeSeries) {
    ctx.strokeStyle = seriesColor(s.field.chartSlot);
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    s.points.forEach((p, i) => {
      const px = xToPx(p.t);
      const py = yToPx(p.v);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();
  }

  // Crosshair + tooltip al passaggio del mouse
  if (state.hover) {
    const hoverT = xMin + (state.hover.x - margin.left) / plotW * (xMax - xMin);
    if (hoverT >= xMin && hoverT <= xMax) {
      const hoverPx = xToPx(hoverT);
      ctx.strokeStyle = mutedColor;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(hoverPx, margin.top);
      ctx.lineTo(hoverPx, margin.top + plotH);
      ctx.stroke();
      ctx.setLineDash([]);

      const lines = [];
      for (const s of activeSeries) {
        const nearest = nearestPoint(s.points, hoverT);
        if (nearest) lines.push({ color: seriesColor(s.field.chartSlot), text: `${s.field.label}: ${nearest.v.toFixed(2)}` });
      }
      drawTooltip(ctx, hoverPx, margin.top, lines, cssWidth);
    }
  }
}

function nearestPoint(points, t) {
  let best = null;
  let bestDist = Infinity;
  for (const p of points) {
    const d = Math.abs(p.t - t);
    if (d < bestDist) { bestDist = d; best = p; }
  }
  return best;
}

function drawTooltip(ctx, x, top, lines, cssWidth) {
  if (lines.length === 0) return;
  const style = getComputedStyle(document.documentElement);
  const surface = style.getPropertyValue("--surface-1").trim();
  const border = style.getPropertyValue("--border").trim();
  const ink = style.getPropertyValue("--text-primary").trim();

  ctx.font = "12px system-ui, sans-serif";
  const padding = 8;
  const lineHeight = 16;
  const textWidth = Math.max(...lines.map((l) => ctx.measureText(l.text).width));
  const boxW = textWidth + padding * 2 + 14;
  const boxH = lines.length * lineHeight + padding * 2;
  let boxX = x + 10;
  if (boxX + boxW > cssWidth) boxX = x - boxW - 10;
  const boxY = top + 4;

  ctx.fillStyle = surface;
  ctx.strokeStyle = border;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(boxX, boxY, boxW, boxH, 6);
  ctx.fill();
  ctx.stroke();

  ctx.textBaseline = "middle";
  lines.forEach((line, i) => {
    const ly = boxY + padding + lineHeight * i + lineHeight / 2;
    ctx.fillStyle = line.color;
    ctx.beginPath();
    ctx.arc(boxX + padding + 3, ly, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = ink;
    ctx.fillText(line.text, boxX + padding + 12, ly);
  });
}

function setupChartHover() {
  const canvas = document.getElementById("chart");
  canvas.addEventListener("mousemove", (ev) => {
    const rect = canvas.getBoundingClientRect();
    state.hover = { x: ev.clientX - rect.left };
    scheduleRedraw();
  });
  canvas.addEventListener("mouseleave", () => {
    state.hover = null;
    scheduleRedraw();
  });
  window.addEventListener("resize", scheduleRedraw);
}

// ---------- Stato connessione ----------

function applyStatus(connected, alive, message) {
  document.getElementById("status-text").textContent = message;
  const pill = document.getElementById("status-pill");
  pill.classList.remove("status-neutral", "status-good", "status-warning", "status-critical");
  if (!connected) {
    pill.classList.add(message.toLowerCase().includes("attesa") ? "status-neutral" : "status-critical");
  } else if (alive === false) {
    pill.classList.add("status-warning");
  } else {
    pill.classList.add("status-good");
  }
}

// ---------- WebSocket ----------

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
  state.ws = ws;

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "status") {
      applyStatus(msg.connected, null, msg.message);
      if (msg.connected) {
        // Nuova connessione: azzeriamo il grafico per non mostrare un
        // salto temporale rispetto alla sessione precedente.
        state.chartStart = performance.now();
        for (const key of state.buffers.keys()) state.buffers.set(key, []);
        scheduleRedraw();
      }
    } else if (msg.type === "snapshot") {
      applyStatus(msg.connected, msg.alive, msg.message);
      updateTiles(msg.snapshot);
      pushChartPoint(msg.snapshot);
      scheduleRedraw();
    }
  };

  ws.onclose = () => {
    setTimeout(connectWebSocket, 1500);
  };
  ws.onerror = () => ws.close();
}

// ---------- Avvio ----------

async function init() {
  state.checked = loadCheckedFields();
  for (const field of ALL_FIELDS) {
    if (field.chartSlot && state.checked.has(field.key)) state.buffers.set(field.key, []);
  }

  buildFieldPicker();
  rebuildTiles();
  rebuildLegend();
  setupChartHover();
  scheduleRedraw();

  try {
    const res = await fetch("/api/default-ip");
    const data = await res.json();
    document.getElementById("ip-input").value = data.ip || "";
  } catch (e) {
    /* ignora, l'utente puo' comunque digitare l'IP a mano */
  }

  document.getElementById("connect-btn").addEventListener("click", async () => {
    const ip = document.getElementById("ip-input").value.trim();
    await fetch("/api/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip }),
    });
  });

  connectWebSocket();
}

init();
