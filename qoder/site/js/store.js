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
    this.items = this.state.items = this.state.items.filter((row) => row.id !== id);
    if (item) this.log(`删除「${item.title}」`);
    this.emit();
  },

  nextPosition() {
    this.positions += 1;
    this.state.positions = this.positions;
    return this.positions;
  },

  addHandoff(record) {
    this.state.handoffs.unshift(record);
    this.log(`生成交接 ${record.from} → ${record.to}（${record.steps.length} 步）`);
    this.emit();
  },

  reset() {
    this.state = this.fresh();
    this.positions = 0;
    this.emit();
  },
};

export { DEFAULT_THRESHOLD, DEFAULT_AS_OF };
