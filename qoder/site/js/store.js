/** 台账状态：种子数据、本地持久化、派生统计与对账动作。 */

import { OPEN_STATUSES, buildIndex, judgeCandidate } from "./engine.js";

const KEY = "relay.workbench.v2";
const DEFAULT_AS_OF = "2026-09-29";
const DEFAULT_THRESHOLD = 0.55;

const clone = (value) => JSON.parse(JSON.stringify(value));

function shortId(prefix) {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}${Date.now().toString(36).slice(-3)}`;
}

export const store = {
  state: null,
  seed: null,
  vectorizer: null,
  vectors: new Map(),
  listeners: [],
  positions: 0,

  async init() {
    this.seed = await this.fetchSeed();
    const saved = this.read();
    this.state = saved || this.fresh();
    this.state.items = this.state.items.map((item) => ({ ...item }));
    this.state.views = Array.isArray(this.state.views) ? this.state.views : [];
    this.state.milestones = { extract: false, write: false, reconcile: false, handoff: false, ...(this.state.milestones || {}) };
    this.rebuild();
    this.positions = Math.max(Number(this.state.positions) || 0, 4 * (this.state.handoffs?.length || 0));
    return this.state;
  },

  async fetchSeed() {
    const [ledger, meetings] = await Promise.all([
      fetch("data/ledger.json").then((r) => {
        if (!r.ok) throw new Error("ledger.json");
        return r.json();
      }),
      fetch("data/meetings.json").then((r) => {
        if (!r.ok) throw new Error("meetings.json");
        return r.json();
      }),
    ]);
    return { items: ledger.items, meetings: meetings.meetings, project: ledger.project || "Aurora" };
  },

  fresh() {
    return {
      version: 2,
      project: this.seed.project || "Aurora",
      asOf: DEFAULT_AS_OF,
      threshold: DEFAULT_THRESHOLD,
      positions: 0,
      items: clone(this.seed.items),
      handoffs: [],
      views: [],
      milestones: { extract: false, write: false, reconcile: false, handoff: false },
      activity: [
        { at: new Date().toISOString(), text: `载入初始台账 ${this.seed.items.length} 条` },
      ],
    };
  },

  read() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || !Array.isArray(parsed.items)) return null;
      return parsed;
    } catch {
      return null;
    }
  },

  save() {
    try {
      localStorage.setItem(KEY, JSON.stringify(this.state));
    } catch {
      /* 隐私模式下忽略 */
    }
  },

  subscribe(fn) { this.listeners.push(fn); },

  emit() {
    this.rebuild();
    this.save();
    this.listeners.forEach((fn) => fn(this.state));
  },

  rebuild() {
    const index = buildIndex(this.state.items);
    this.vectorizer = index.vectorizer;
    this.vectors = index.vectors;
  },

  get items() { return this.state.items; },
  get asOf() { return this.state.asOf; },
  get threshold() { return this.state.threshold; },

  isOpen(item) { return OPEN_STATUSES.includes(item.status); },

  overdue(asOf = this.state.asOf) {
    return this.items.filter((item) => this.isOpen(item) && item.due && item.due < asOf);
  },

  unassigned() {
    return this.items.filter((item) => this.isOpen(item) && !item.owner);
  },

  stats(asOf = this.state.asOf) {
    const open = this.items.filter((item) => this.isOpen(item));
    return {
      total: this.items.length,
      open: open.length,
      done: this.items.filter((item) => item.status === "done").length,
      overdue: this.overdue(asOf).length,
      unassigned: this.unassigned().length,
      risks: this.items.filter((item) => item.kind === "risk" && item.status !== "done").length,
    };
  },

  judge(candidate) {
    return judgeCandidate(this.vectorizer, this.vectors, this.items, candidate, this.state.threshold);
  },

  setAsOf(value) {
    this.state.asOf = value;
    this.emit();
  },

  setThreshold(value) {
    this.state.threshold = value;
    this.emit();
  },

  log(text) {
    this.state.activity.unshift({ at: new Date().toISOString(), text });
    this.state.activity = this.state.activity.slice(0, 40);
  },

  writeCandidates(candidates) {
    let added = 0;
    let merged = 0;
    for (const candidate of candidates) {
      if (candidate.merge && candidate.matchedId && this.items.some((item) => item.id === candidate.matchedId)) {
        this.merge(candidate, candidate.matchedId);
        merged += 1;
      } else {
        this.items.unshift({
          id: shortId("it"),
          kind: candidate.kind,
          title: candidate.title,
          detail: candidate.detail,
          owner: candidate.owner || "",
          due: candidate.due || "",
          status: candidate.status || "open",
          source: candidate.source || "手动录入",
        });
        added += 1;
      }
    }
    this.log(`写入台账：新增 ${added} 条，合并 ${merged} 条`);
    this.state.milestones.write = true;
    this.emit();
    return { added, merged };
  },

  merge(candidate, targetId) {
    const target = this.items.find((item) => item.id === targetId);
    if (!target) return;
    target.detail = candidate.detail || target.detail;
    target.owner = candidate.owner || target.owner;
    target.due = candidate.due || target.due;
    if (candidate.status === "done") target.status = "done";
    else if (candidate.status !== "open" && target.status === "open") target.status = candidate.status;
    if (candidate.source && target.source && !target.source.includes(candidate.source)) {
      target.source = `${target.source} → ${candidate.source}`;
    }
  },

  addItem(item) {
    const created = {
      id: shortId("it"),
      kind: item.kind || "action",
      title: item.title || "未命名条目",
      detail: item.detail || "",
      owner: item.owner || "",
      due: item.due || "",
      status: item.status || "open",
      source: item.source || "手动新增",
    };
    this.items.unshift(created);
    this.log(`新增条目「${created.title}」`);
    this.emit();
    return created;
  },

  updateItem(id, patch) {
    const item = this.items.find((row) => row.id === id);
    if (!item) return;
    Object.assign(item, patch);
    this.log(`更新「${item.title}」`);
    this.emit();
  },

  setStatus(id, status) {
    const item = this.items.find((row) => row.id === id);
    if (!item || item.status === status) return;
    const before = item.status;
    item.status = status;
    this.log(`「${item.title}」${before} → ${status}`);
    this.emit();
  },

  removeItem(id) {
    const item = this.items.find((row) => row.id === id);
    if (!item) return;
    this.snapshot(`删除「${item.title}」`);
    this.state.items = this.state.items.filter((row) => row.id !== id);
    this.log(`删除「${item.title}」`);
    this.emit();
  },

  nextPosition() {
    this.positions += 1;
    this.state.positions = this.positions;
    return this.positions;
  },

  addHandoff(record) {
    this.state.handoffs.unshift(record);
    this.state.milestones.handoff = true;
    this.log(`生成交接 ${record.from} → ${record.to}（${record.steps.length} 步）`);
    this.emit();
  },

  mark(key) {
    if (!this.state.milestones || this.state.milestones[key]) return;
    this.state.milestones[key] = true;
    this.save();
  },

  /* ---------- 批量操作与撤销 ---------- */

  snapshot(label) {
    this._undo = {
      label,
      items: clone(this.state.items),
      handoffs: clone(this.state.handoffs),
    };
  },

  get undoLabel() { return this._undo?.label || ""; },

  undo() {
    if (!this._undo) return false;
    this.state.items = this._undo.items;
    this.state.handoffs = this._undo.handoffs;
    this.log(`撤销：${this._undo.label}`);
    this._undo = null;
    this.emit();
    return true;
  },

  bulkStatus(ids, status) {
    const set = new Set(ids);
    const touched = this.items.filter((item) => set.has(item.id) && item.status !== status);
    if (!touched.length) return 0;
    this.snapshot(`批量改状态 ${touched.length} 条`);
    touched.forEach((item) => { item.status = status; });
    this.log(`批量把 ${touched.length} 条改为「${status}」`);
    this.emit();
    return touched.length;
  },

  bulkRemove(ids) {
    const set = new Set(ids);
    const removed = this.items.filter((item) => set.has(item.id));
    if (!removed.length) return 0;
    this.snapshot(`删除 ${removed.length} 条`);
    this.state.items = this.items.filter((item) => !set.has(item.id));
    this.log(`批量删除 ${removed.length} 条`);
    this.emit();
    return removed.length;
  },

  /** 拖拽排序：把 dragId 挪到 targetId 前/后，直接改数组顺序。 */
  reorder(dragId, targetId, after = false) {
    if (dragId === targetId) return false;
    const from = this.items.findIndex((item) => item.id === dragId);
    const to = this.items.findIndex((item) => item.id === targetId);
    if (from < 0 || to < 0) return false;
    const [moved] = this.state.items.splice(from, 1);
    const base = this.items.findIndex((item) => item.id === targetId);
    this.state.items.splice(after ? base + 1 : base, 0, moved);
    this.log(`调整顺序「${moved.title}」`);
    this.emit();
    return true;
  },

  /* ---------- 保存的筛选视图 ---------- */

  saveView(name, filters) {
    const view = { id: shortId("vw"), name, filters: { ...filters } };
    this.state.views.push(view);
    this.log(`保存视图「${name}」`);
    this.emit();
    return view;
  },

  removeView(id) {
    const view = this.state.views.find((row) => row.id === id);
    this.state.views = this.state.views.filter((row) => row.id !== id);
    if (view) this.log(`删除视图「${view.name}」`);
    this.emit();
  },

  reset() {
    this.state = this.fresh();
    this.positions = 0;
    this._undo = null;
    this.emit();
  },
};

export { DEFAULT_THRESHOLD, DEFAULT_AS_OF };
