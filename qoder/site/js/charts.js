/** 纯 SVG / HTML 图形组件：不引第三方库，数据全部来自当前台账。 */

import { esc } from "./ui.js";
import { KIND_COLOR } from "./icons.js";

let uid = 0;
const nextId = (prefix) => `${prefix}${(uid += 1)}`;

const polar = (cx, cy, r, deg) => {
  const rad = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
};

/** 环形构成图：中心放总数，右侧图例带数值与占比。 */
export function donut(segments, { size = 168, thickness = 20, centerValue, centerLabel } = {}) {
  const total = segments.reduce((sum, seg) => sum + seg.value, 0);
  const r = (size - thickness) / 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  let offset = 0;

  const arcs = total
    ? segments.filter((seg) => seg.value > 0).map((seg) => {
      const len = (seg.value / total) * circ;
      const dash = Math.max(len - 2.5, 0.6);
      const arc = `<circle class="donut-arc" cx="${c}" cy="${c}" r="${r}" fill="none"
        stroke="${seg.color}" stroke-width="${thickness}" stroke-linecap="round"
        stroke-dasharray="${dash.toFixed(2)} ${(circ - dash).toFixed(2)}"
        stroke-dashoffset="${(-offset).toFixed(2)}"
        transform="rotate(-90 ${c} ${c})"><title>${esc(seg.label)} ${seg.value}</title></circle>`;
      offset += len;
      return arc;
    }).join("")
    : `<circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="#e7e3dd" stroke-width="${thickness}"/>`;

  const legend = segments.map((seg) => `
    <li>
      <i style="background:${seg.color}"></i>
      <span>${esc(seg.label)}</span>
      <b>${seg.value}</b>
      <em>${total ? Math.round((seg.value / total) * 100) : 0}%</em>
    </li>`).join("");

  return `
    <div class="donut-wrap">
      <svg class="donut" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="构成图">
        ${arcs}
        <text x="${c}" y="${c - 2}" text-anchor="middle" class="donut-num">${centerValue ?? total}</text>
        <text x="${c}" y="${c + 16}" text-anchor="middle" class="donut-cap">${esc(centerLabel || "合计")}</text>
      </svg>
      <ul class="donut-legend">${legend}</ul>
    </div>`;
}

/** 小进度环，用在 KPI 卡右上角。 */
export function ring(pct, { size = 46, thickness = 5, color = "#d9542b", label = "" } = {}) {
  const r = (size - thickness) / 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  const value = Math.max(0, Math.min(1, pct));
  return `
    <svg class="ring" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="${esc(label)} ${Math.round(value * 100)}%">
      <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="#ece7e1" stroke-width="${thickness}"/>
      <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${color}" stroke-width="${thickness}"
        stroke-linecap="round" stroke-dasharray="${(value * circ).toFixed(2)} ${circ.toFixed(2)}"
        transform="rotate(-90 ${c} ${c})"/>
      <text x="${c}" y="${c + 3.6}" text-anchor="middle" class="ring-num">${Math.round(value * 100)}</text>
    </svg>`;
}

/** 迷你面积趋势线。 */
export function spark(values, { w = 132, h = 34, color = "#d9542b" } = {}) {
  if (!values.length) return "";
  const id = nextId("sp");
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const step = values.length > 1 ? w / (values.length - 1) : w;
  const pts = values.map((value, index) => [index * step, h - 3 - ((value - min) / span) * (h - 8)]);
  const line = pts.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${line} L${w} ${h} L0 ${h} Z`;
  const last = pts[pts.length - 1];
  return `
    <svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity=".28"/>
        <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
      </linearGradient></defs>
      <path d="${area}" fill="url(#${id})"/>
      <path d="${line}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.6" fill="${color}"/>
    </svg>`;
}

/** 横向堆叠条：一行看清构成。 */
export function stacked(segments, { height = 12 } = {}) {
  const total = segments.reduce((sum, seg) => sum + seg.value, 0) || 1;
  return `
    <div class="stacked" style="height:${height}px">
      ${segments.filter((seg) => seg.value > 0).map((seg) => `
        <i style="width:${((seg.value / total) * 100).toFixed(2)}%;background:${seg.color}" title="${esc(seg.label)} ${seg.value}"></i>`).join("")}
    </div>`;
}

/** 到期时间轴：横轴是日期，竖线是基准日，点按类型着色，可点开条目。 */
export function dueTimeline(items, asOf, { width = 640, laneGap = 26 } = {}) {
  const dated = items
    .filter((item) => item.due)
    .map((item) => ({ ...item, t: Date.parse(`${item.due}T00:00:00`) }))
    .filter((item) => Number.isFinite(item.t))
    .sort((a, b) => a.t - b.t);
  if (!dated.length) return `<div class="empty">还没有带截止日的事项</div>`;

  const today = Date.parse(`${asOf}T00:00:00`);
  const day = 86400000;
  const min = Math.min(dated[0].t, today) - 2 * day;
  const max = Math.max(dated[dated.length - 1].t, today) + 2 * day;
  const padL = 16;
  const padR = 16;
  const inner = width - padL - padR;
  const xOf = (t) => padL + ((t - min) / (max - min)) * inner;

  const lanes = [];
  const placed = dated.slice(0, 14).map((item) => {
    const x = xOf(item.t);
    let lane = lanes.findIndex((lastX) => x - lastX >= laneGap);
    if (lane === -1) { lane = lanes.length; lanes.push(x); } else { lanes[lane] = x; }
    return { item, x, lane };
  });

  const laneCount = Math.max(lanes.length, 1);
  const top = 26;
  const height = top + laneCount * 24 + 30;
  const axisY = height - 20;
  const todayX = xOf(today);
  const ticks = [min + 2 * day, today, max - 2 * day];
  const fmt = (t) => {
    const d = new Date(t);
    return `${d.getMonth() + 1}.${String(d.getDate()).padStart(2, "0")}`;
  };

  return `
    <svg class="timeline" viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img" aria-label="到期时间轴">
      <line x1="${padL}" y1="${axisY}" x2="${width - padR}" y2="${axisY}" stroke="#e2ddd6" stroke-width="1.4"/>
      ${ticks.map((t) => `
        <line x1="${xOf(t).toFixed(1)}" y1="${axisY - 4}" x2="${xOf(t).toFixed(1)}" y2="${axisY + 4}" stroke="#cfc8bf"/>
        <text x="${xOf(t).toFixed(1)}" y="${axisY + 16}" text-anchor="middle" class="tl-tick">${fmt(t)}</text>`).join("")}
      <line x1="${todayX.toFixed(1)}" y1="12" x2="${todayX.toFixed(1)}" y2="${axisY}" stroke="#d9542b" stroke-width="1.4" stroke-dasharray="4 4"/>
      <text x="${todayX.toFixed(1)}" y="9" text-anchor="middle" class="tl-now">基准日</text>
      ${placed.map(({ item, x, lane }) => {
        const y = top + lane * 24;
        const color = KIND_COLOR[item.kind] || "#8b95a7";
        const late = item.t < today;
        return `
          <g class="tl-dot" data-item="${esc(item.id)}" tabindex="0" role="button">
            <title>${esc(item.title)}｜${esc(item.due)}${late ? "｜已超期" : ""}</title>
            <line x1="${x.toFixed(1)}" y1="${y + 7}" x2="${x.toFixed(1)}" y2="${axisY}" stroke="${color}" stroke-opacity=".22" stroke-width="1.2"/>
            <circle cx="${x.toFixed(1)}" cy="${y}" r="${late ? 6.5 : 5.5}" fill="${color}" fill-opacity="${late ? 1 : 0.85}" stroke="#fff" stroke-width="1.6"/>
            ${late ? `<circle cx="${x.toFixed(1)}" cy="${y}" r="10" fill="none" stroke="${color}" stroke-opacity=".3"/>` : ""}
          </g>`;
      }).join("")}
    </svg>`;
}

/** 判重距离标尺：把「离阈值还有多远」画出来。 */
export function distanceMeter(distance, threshold) {
  if (!Number.isFinite(distance)) return `<div class="meter empty-meter"><span>台账为空，全部按新增处理</span></div>`;
  const scale = Math.max(0.9, distance + 0.08, threshold + 0.12);
  const pct = Math.min(100, (distance / scale) * 100);
  const mark = Math.min(100, (threshold / scale) * 100);
  const merge = distance <= threshold;
  return `
    <div class="meter ${merge ? "merge" : "fresh"}">
      <div class="meter-track">
        <i style="width:${pct.toFixed(1)}%"></i>
        <u style="left:${mark.toFixed(1)}%" title="阈值 ${threshold.toFixed(2)}"></u>
      </div>
      <div class="meter-cap"><b>${distance.toFixed(3)}</b><span>阈值 ${threshold.toFixed(2)}</span></div>
    </div>`;
}

/** 检索分数条。 */
export function scoreBar(value, max, color) {
  const pct = max > 0 ? Math.max(3, Math.min(100, (value / max) * 100)) : 0;
  return `<span class="score-bar"><i style="width:${pct.toFixed(1)}%;background:${color}"></i></span>`;
}

/** 热力单元格底色：数量越多越暖。 */
export function heatStyle(count, max) {
  if (!count) return "";
  const alpha = 0.08 + (count / Math.max(max, 1)) * 0.42;
  return `background:rgba(217,84,43,${alpha.toFixed(3)});color:#7a2c12;font-weight:600`;
}

/** 半圆仪表：完成率。 */
export function gauge(pct, { width = 168, color = "#0f9d76", label = "完成率" } = {}) {
  const value = Math.max(0, Math.min(1, pct));
  const height = width * 0.62;
  const cx = width / 2;
  const cy = height - 12;
  const r = width / 2 - 14;
  const [sx, sy] = polar(cx, cy, r, -90);
  const [ex, ey] = polar(cx, cy, r, 90);
  const [vx, vy] = polar(cx, cy, r, -90 + value * 180);
  const large = value > 0.5 ? 1 : 0;
  const id = nextId("gg");
  return `
    <svg class="gauge" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="${esc(label)} ${Math.round(value * 100)}%">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#f0803c"/><stop offset="55%" stop-color="#d9542b"/><stop offset="100%" stop-color="${color}"/>
      </linearGradient></defs>
      <path d="M${sx} ${sy} A${r} ${r} 0 0 1 ${ex} ${ey}" fill="none" stroke="#ece7e1" stroke-width="12" stroke-linecap="round"/>
      ${value > 0 ? `<path d="M${sx} ${sy} A${r} ${r} 0 ${large} 1 ${vx.toFixed(2)} ${vy.toFixed(2)}" fill="none" stroke="url(#${id})" stroke-width="12" stroke-linecap="round"/>` : ""}
      <text x="${cx}" y="${cy - 6}" text-anchor="middle" class="gauge-num">${Math.round(value * 100)}%</text>
      <text x="${cx}" y="${cy + 12}" text-anchor="middle" class="gauge-cap">${esc(label)}</text>
    </svg>`;
}