/** 统一图标库：24×24 线性图标，随字色走，避免每个视图各画各的。 */

import { esc } from "./ui.js";

const PATHS = {
  grid: '<path d="M4 13h6V4H4zM14 20h6v-9h-6zM4 20h6v-4H4zM14 8h6V4h-6z"/>',
  inbox: '<path d="M12 3v11m0 0 4-4m-4 4-4-4"/><path d="M4 17v3h16v-3"/>',
  ledger: '<path d="M4 5h16M4 12h16M4 19h10"/><circle cx="19" cy="19" r="2"/>',
  reconcile: '<path d="M3 17l5-6 4 3 4-7 5 4"/><path d="M3 21h18"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="M16 16l4 4"/>',
  handoff: '<path d="M5 12h13"/><path d="M13 6l6 6-6 6"/><path d="M5 6v12"/>',
  baton: '<rect x="3" y="9" width="13" height="6" rx="3"/><path d="M16 12h5"/><path d="M18.5 9.5 21 12l-2.5 2.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="M8 12.4l2.6 2.6L16 9.4"/>',
  circle: '<circle cx="12" cy="12" r="8"/>',
  dot: '<circle cx="12" cy="12" r="3.4"/>',
  alert: '<path d="M12 3.6 21 19H3z"/><path d="M12 9.5v4.2"/><circle cx="12" cy="16.6" r=".7"/>',
  shield: '<path d="M12 3l7 3v6c0 4.2-2.9 7.4-7 9-4.1-1.6-7-4.8-7-9V6z"/><path d="M9.4 12.2l1.9 1.9 3.4-3.6"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.4V12l3 1.8"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3.2v3.4M16 3.2v3.4"/>',
  user: '<circle cx="12" cy="8.4" r="3.6"/><path d="M4.8 20c1.1-3.6 3.9-5.4 7.2-5.4S18.1 16.4 19.2 20"/>',
  users: '<circle cx="9.4" cy="8.6" r="3.3"/><path d="M3.4 19.4c.9-3.2 3.2-4.8 6-4.8s5.1 1.6 6 4.8"/><path d="M16.4 6.2a3.2 3.2 0 0 1 0 6M18 14.9c2 .6 3.3 2.1 3.8 4.5"/>',
  userOff: '<circle cx="12" cy="8.4" r="3.6"/><path d="M4.8 20c1.1-3.6 3.9-5.4 7.2-5.4"/><path d="M16.5 16.5l4.5 4.5M21 16.5l-4.5 4.5"/>',
  flag: '<path d="M6 21V4"/><path d="M6 4.6h11.5l-2.2 3.9 2.2 3.9H6"/>',
  target: '<circle cx="12" cy="12" r="8.4"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r=".8"/>',
  zap: '<path d="M13.4 3 5.6 13.4h5.2L10 21l8-10.6h-5.2z"/>',
  sparkles: '<path d="M12 4.2l1.5 3.9 3.9 1.5-3.9 1.5L12 15l-1.5-3.9L6.6 9.6l3.9-1.5z"/><path d="M18.4 15.2l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>',
  layers: '<path d="M12 3.6 3.6 8 12 12.4 20.4 8z"/><path d="M4 12.4 12 16.7l8-4.3"/><path d="M4 16.6 12 21l8-4.4"/>',
  database: '<ellipse cx="12" cy="6.2" rx="7.4" ry="3"/><path d="M4.6 6.2v11.6c0 1.7 3.3 3 7.4 3s7.4-1.3 7.4-3V6.2"/><path d="M4.6 12c0 1.7 3.3 3 7.4 3s7.4-1.3 7.4-3"/>',
  merge: '<path d="M7 20V9.6a4 4 0 0 1 4-4h6"/><path d="M14 2.6 17.4 5.6 14 8.6"/><path d="M7 14.4c0 3 2.4 5.6 5.4 5.6H17"/>',
  split: '<path d="M6 4v4.6a4 4 0 0 0 4 4h8"/><path d="M15 9.6l3.4 3-3.4 3"/><path d="M6 20v-4"/>',
  filter: '<path d="M4 5.4h16l-6.2 7.3V19l-3.6 1.8v-8.1z"/>',
  sort: '<path d="M7 4v16m0 0-3-3.2M7 20l3-3.2"/><path d="M17 20V4m0 0-3 3.2M17 4l3 3.2"/>',
  drag: '<circle cx="9" cy="6" r="1.3"/><circle cx="15" cy="6" r="1.3"/><circle cx="9" cy="12" r="1.3"/><circle cx="15" cy="12" r="1.3"/><circle cx="9" cy="18" r="1.3"/><circle cx="15" cy="18" r="1.3"/>',
  bookmark: '<path d="M6.5 3.6h11a1 1 0 0 1 1 1v15.8l-6.5-4-6.5 4V4.6a1 1 0 0 1 1-1z"/>',
  save: '<path d="M5 4.6h11L19.4 8v11.4a1 1 0 0 1-1 1H5.6a1 1 0 0 1-1-1V5.6a1 1 0 0 1 1-1z"/><path d="M8.4 4.6v5h7v-5M8.4 20.4v-5.6h7v5.6"/>',
  undo: '<path d="M4.6 9.4h9.2a5.2 5.2 0 0 1 0 10.4H8"/><path d="M7.8 5.2 4 9.4l3.8 4.2"/>',
  refresh: '<path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20.4 4v4.6h-4.6"/>',
  trash: '<path d="M4.6 6.6h14.8M9.4 6.6V4.4h5.2v2.2"/><path d="M6.6 6.6 7.6 20a1 1 0 0 0 1 .9h6.8a1 1 0 0 0 1-.9l1-13.4"/><path d="M10.4 10.6v6.4M13.6 10.6v6.4"/>',
  edit: '<path d="M4.6 19.4h4l10-10a2.1 2.1 0 0 0-3-3l-10 10z"/><path d="M14.4 6.6l3 3"/>',
  copy: '<rect x="8.6" y="8.6" width="11" height="11" rx="2"/><path d="M15.4 5.6a2 2 0 0 0-2-2H6.6a2 2 0 0 0-2 2v6.8a2 2 0 0 0 2 2"/>',
  download: '<path d="M12 3.6v11m0 0 4-4m-4 4-4-4"/><path d="M4.6 17v3.4h14.8V17"/>',
  file: '<path d="M6.4 3.6h7L18.6 9v11.4H6.4z"/><path d="M13.2 3.6V9h5.4"/><path d="M9.2 13h6M9.2 16.6h4.4"/>',
  info: '<circle cx="12" cy="12" r="8.6"/><path d="M12 11v5.4"/><circle cx="12" cy="7.9" r=".8"/>',
  help: '<circle cx="12" cy="12" r="8.6"/><path d="M9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .9-1 1.7v.4"/><circle cx="12" cy="17" r=".8"/>',
  play: '<path d="M8 5.4 18.4 12 8 18.6z"/>',
  arrowRight: '<path d="M4.6 12h14"/><path d="M13.4 6.6 18.8 12l-5.4 5.4"/>',
  arrowUpRight: '<path d="M7 17 17 7"/><path d="M9 7h8v8"/>',
  chevronRight: '<path d="M9.4 5.6 15.8 12l-6.4 6.4"/>',
  chevronLeft: '<path d="M14.6 5.6 8.2 12l6.4 6.4"/>',
  chevronDown: '<path d="M5.6 9.4 12 15.8l6.4-6.4"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2.6v3m0 12.8v3M2.6 12h3m12.8 0h3M5.2 5.2l2.1 2.1m9.4 9.4 2.1 2.1M18.8 5.2 16.7 7.3m-9.4 9.4-2.1 2.1"/>',
  trendUp: '<path d="M3.6 16.6 9 11l3.4 3.2 7-7.4"/><path d="M15.4 6.8h4.4v4.4"/>',
  trendDown: '<path d="M3.6 7.4 9 13l3.4-3.2 7 7.4"/><path d="M15.4 17.2h4.4v-4.4"/>',
  link: '<path d="M10.4 13.6a3.6 3.6 0 0 0 5.2 0l2.8-2.8a3.7 3.7 0 0 0-5.2-5.2l-1.4 1.4"/><path d="M13.6 10.4a3.6 3.6 0 0 0-5.2 0l-2.8 2.8a3.7 3.7 0 0 0 5.2 5.2l1.4-1.4"/>',
  lock: '<rect x="5" y="10.4" width="14" height="9.6" rx="2"/><path d="M8.4 10.4V7.8a3.6 3.6 0 0 1 7.2 0v2.6"/>',
  message: '<path d="M4.4 5.6h15.2v10.2H9.6L4.4 19.4z"/><path d="M8.4 9.6h7.2M8.4 12.6h4.6"/>',
  branch: '<circle cx="7" cy="6" r="2.4"/><circle cx="7" cy="18" r="2.4"/><circle cx="17" cy="9.4" r="2.4"/><path d="M7 8.4v7.2"/><path d="M17 11.8c0 3-2.6 4.2-5.4 4.6"/>',
  eye: '<path d="M2.6 12S6 6.4 12 6.4 21.4 12 21.4 12 18 17.6 12 17.6 2.6 12 2.6 12z"/><circle cx="12" cy="12" r="2.8"/>',
  compass: '<circle cx="12" cy="12" r="8.6"/><path d="M15.4 8.6 13.6 13.6 8.6 15.4l1.8-5z"/>',
  route: '<circle cx="6" cy="6.4" r="2.4"/><circle cx="18" cy="17.6" r="2.4"/><path d="M8.4 6.4h5.2a3.4 3.4 0 0 1 0 6.8h-3.2a3.4 3.4 0 0 0 0 6.8h5.2"/>',
  bell: '<path d="M6.4 10.4a5.6 5.6 0 0 1 11.2 0c0 4 1.4 5.6 1.4 5.6H5s1.4-1.6 1.4-5.6z"/><path d="M10.2 19a2 2 0 0 0 3.6 0"/>',
  pin: '<path d="M12 21s6.4-6 6.4-10.4a6.4 6.4 0 1 0-12.8 0C5.6 15 12 21 12 21z"/><circle cx="12" cy="10.4" r="2.4"/>',
};

export function icon(name, className = "") {
  const body = PATHS[name] || PATHS.circle;
  return `<svg class="ic${className ? ` ${className}` : ""}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${body}</svg>`;
}

export const KIND_ICON = { decision: "shield", action: "zap", risk: "alert", question: "help" };
export const STATUS_ICON = {
  open: "circle",
  in_progress: "play",
  blocked: "lock",
  done: "checkCircle",
  stale: "minus",
};

/** 类型 / 状态对应的色号，图表、图标、标签共用一套。 */
export const KIND_COLOR = {
  decision: "#0d7d8a",
  action: "#2563eb",
  risk: "#e11d48",
  question: "#d97706",
};
export const STATUS_COLOR = {
  open: "#8b95a7",
  in_progress: "#2563eb",
  blocked: "#e11d48",
  done: "#059669",
  stale: "#8b5cf6",
};

const OWNER_HUES = [18, 196, 262, 152, 330, 42, 210, 286];

export function ownerHue(name) {
  const text = String(name || "无人认领");
  let hash = 0;
  for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) % 9973;
  return OWNER_HUES[hash % OWNER_HUES.length];
}

export function avatar(name, size = 24) {
  const label = String(name || "?").trim();
  const initial = label ? label.slice(0, 1) : "?";
  const hue = ownerHue(label);
  const empty = !label;
  return `<span class="avatar-c${empty ? " empty" : ""}" style="--h:${hue};width:${size}px;height:${size}px;font-size:${Math.round(size * 0.44)}px" title="${esc(label || "无人认领")}">${esc(empty ? "?" : initial)}</span>`;
}