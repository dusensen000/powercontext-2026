/** 六个工作视图。每个视图返回 HTML，mount 里绑定自己的交互。 */

import {
  KIND_LABEL,
  STATUS_LABEL,
  KINDS,
  STATUSES,
  extractMeeting,
  tokenize,
  search as runSearch,
} from "./engine.js";
import { store } from "./store.js";
import {
  $, $$, esc, daysBetween, fmtDate, fmtStmt, fmtTime, toast,
  openDrawer, closeDrawer, openModal, closeModal, copyText, download, confirmDialog,
} from "./ui.js";
import { icon, KIND_ICON, KIND_COLOR, STATUS_COLOR, avatar, ownerHue } from "./icons.js";
import { donut, ring, stacked, dueTimeline, distanceMeter, scoreBar, heatStyle, gauge } from "./charts.js";
import { MILESTONES, progress, startTour } from "./onboard.js";

const KIND_ORDER = { risk: 0, action: 1, decision: 2, question: 3 };
const STATUS_ORDER = { open: 0, blocked: 1, in_progress: 2, done: 3, stale: 4 };

const kindPill = (kind, label) => `<span class="pill ${kind}">${icon(KIND_ICON[kind] || "dot")}${esc(label)}</span>`;
const statusPill = (status, label) => `<span class="status-pill ${status}">${esc(label)}</span>`;

const byUrgency = (a, b) => {
  const s = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
  if (s) return s;
  const d = (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9);
  if (d) return d;
  return (a.due || "9999").localeCompare(b.due || "9999");
};

const refresh = () => document.dispatchEvent(new CustomEvent("relay:rerender"));

function section(title, sub, body, right = "", ic = "") {
  return `
    <section class="card">
      <div class="card-head">
        <h2>${ic ? icon(ic) : ""}${esc(title)}</h2>
        ${sub ? `<span class="sub">${esc(sub)}</span>` : ""}
        ${right ? `<div class="right">${right}</div>` : ""}
      </div>
      ${body}
    </section>`;
}

function howto(text, actionLabel = "", actionView = "", extra = "") {
  return `
    <div class="howto">
      ${icon("compass")}
      <span>${text}</span>
      <div class="right">
        ${extra}
        ${actionLabel ? `<button class="btn sm" type="button" data-go="${actionView}">${esc(actionLabel)} ${icon("arrowRight")}</button>` : ""}
      </div>
    </div>`;
}

function emptyState(title, hint, actionLabel = "", actionView = "", ic = "inbox") {
  return `
    <div class="empty">
      ${icon(ic)}
      <b>${esc(title)}</b>${esc(hint)}
      ${actionLabel ? `<div><button class="btn sm primary" type="button" data-go="${actionView}">${esc(actionLabel)}</button></div>` : ""}
    </div>`;
}

function dueTag(item, asOf) {
  if (!item.due) return "";
  const delta = daysBetween(asOf, item.due);
  if (delta === null) return "";
  if (item.status === "done") return `<span class="tag">${esc(fmtDate(item.due))}</span>`;
  if (delta < 0) return `<span class="tag due">逾期 ${-delta} 天</span>`;
  return `<span class="tag">还有 ${delta} 天</span>`;
}

function ownerLoad(items) {
  const map = new Map();
  for (const item of items) {
    if (!store.isOpen(item)) continue;
    const key = item.owner || "";
    map.set(key, (map.get(key) || 0) + 1);
  }
  const rows = [...map.entries()].sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...rows.map((row) => row[1]));
  return `
    <div class="owners">
      ${rows.map(([owner, count]) => `
        <div class="owner-row" style="--h:${ownerHue(owner)}">
          ${avatar(owner, 24)}
          <b>${esc(owner || "无人认领")}</b>
          <i><u style="width:${(count / max) * 100}%"></u></i>
          <em>${count}</em>
        </div>`).join("") || emptyState("没有未完成事项", "台账已经清空了", "", "", "checkCircle")}
    </div>`;
}

function kindBars(items) {
  const counts = KINDS.map((kind) => [kind, items.filter((item) => item.kind === kind).length]);
  const max = Math.max(1, ...counts.map((row) => row[1]));
  return `
    <div class="bars">
      ${counts.map(([kind, count]) => `
        <div class="bar-row">
          <span style="color:${KIND_COLOR[kind]}">${icon(KIND_ICON[kind])}${esc(KIND_LABEL[kind])}</span>
          <i><u style="width:${(count / max) * 100}%;background:linear-gradient(90deg,${KIND_COLOR[kind]}99,${KIND_COLOR[kind]})"></u></i>
          <em>${count}</em>
        </div>`).join("")}
    </div>`;
}

function statusSegments(items) {
  return STATUSES.map((status) => ({
    label: STATUS_LABEL[status],
    value: items.filter((item) => item.status === status).length,
    color: STATUS_COLOR[status],
  }));
}

function kindSegments(items) {
  return KINDS.map((kind) => ({
    label: KIND_LABEL[kind],
    value: items.filter((item) => item.kind === kind).length,
    color: KIND_COLOR[kind],
  }));
}

/* ================================================================== */
/* 概览                                                                */
/* ================================================================== */

export const overview = {
  title: "概览",
  sub: () => `${store.state.project} 登录改造 · ${store.asOf} 对账`,

  render() {
    const stats = store.stats();
    const items = [...store.items].sort(byUrgency);
    const openItems = store.items.filter((item) => store.isOpen(item));
    const risks = items.filter((item) => item.kind === "risk" && item.status !== "done");
    const active = store.state.activity.slice(0, 7);
    const prog = progress();
    const ratio = (n) => (stats.open ? n / stats.open : 0);

    const chain = [
      { key: "extract", view: "ingest", ic: "inbox", title: "读纪要 · 抽条目", text: "决定 / 行动项 / 风险 / 待确认" },
      { key: "write", view: "ingest", ic: "merge", title: "判重 · 写台账", text: `余弦距离 ≤ ${store.threshold.toFixed(2)} 判合并` },
      { key: "reconcile", view: "reconcile", ic: "reconcile", title: "对账", text: "超期 / 无人认领 / 受阻 / 待确认" },
      { key: "handoff", view: "handoff", ic: "handoff", title: "交接", text: "契约 → 交接 → 回执 → 结果" },
    ];

    return `
      <div class="hero">
        <div class="hero-top">
          <div class="hero-copy">
            <span class="hero-eyebrow">${icon("baton")} 接力棒 Relay · 任务交接与进度对账</span>
            <h2>把会上说过的同一件事，收成<em>一条能交接的台账</em></h2>
            <p>贴纪要 → 抽条目 → 和台账判重合并 → 按基准日对账 → 生成带状态的交接卡。下面四步会随你的操作亮起。</p>
          </div>
          <div class="hero-actions">
            <button class="btn primary" type="button" data-go="ingest">${icon("inbox")} 开始录入纪要</button>
            <button class="btn" type="button" id="heroTour">${icon("play")} 分步引导</button>
          </div>
        </div>
        <div class="chain">
          ${chain.map((step, index) => {
            const done = Boolean(store.state.milestones?.[step.key]);
            return `
              <button class="chain-step ${done ? "done" : ""}" type="button" data-go="${step.view}">
                <span class="cs-top"><span class="cs-no">${done ? "✓" : index + 1}</span>${icon(step.ic)}</span>
                <b>${esc(step.title)}</b>
                <small>${esc(step.text)}</small>
                <span class="cs-state">${done ? "已完成" : "待完成"}</span>
              </button>`;
          }).join("")}
        </div>
      </div>

      <div class="kpis">
        <div class="kpi">
          <div class="kpi-head">${icon("layers")}<span>台账条目</span></div>
          <b>${stats.total}</b><small>${stats.open} 条未完成</small>
          <div class="kpi-viz" style="width:74px">${stacked(kindSegments(store.items), { height: 8 })}</div>
        </div>
        <div class="kpi k-green">
          <div class="kpi-head">${icon("checkCircle")}<span>已完成</span></div>
          <b>${stats.done}</b><small>完成率 ${stats.total ? Math.round((stats.done / stats.total) * 100) : 0}%</small>
          <div class="kpi-viz">${ring(stats.total ? stats.done / stats.total : 0, { color: "#0f7a52", label: "完成率" })}</div>
        </div>
        <div class="kpi k-red ${stats.overdue ? "alert" : ""}">
          <div class="kpi-head">${icon("clock")}<span>已超期</span></div>
          <b>${stats.overdue}</b><small>基准日 ${esc(store.asOf)}</small>
          <div class="kpi-viz">${ring(ratio(stats.overdue), { color: "#d92d20", label: "占未完成" })}</div>
        </div>
        <div class="kpi k-amber ${stats.unassigned ? "warn" : ""}">
          <div class="kpi-head">${icon("userOff")}<span>无人认领</span></div>
          <b>${stats.unassigned}</b><small>未完成且无负责人</small>
          <div class="kpi-viz">${ring(ratio(stats.unassigned), { color: "#b45309", label: "占未完成" })}</div>
        </div>
        <div class="kpi k-blue ${stats.risks ? "warn" : ""}">
          <div class="kpi-head">${icon("alert")}<span>未关闭风险</span></div>
          <b>${stats.risks}</b><small>交接前必须先看</small>
          <div class="kpi-viz">${ring(ratio(stats.risks), { color: "#2563eb", label: "占未完成" })}</div>
        </div>
      </div>

      <div class="grid-2">
        <section class="card">
          <div class="card-head">
            <h2>${icon("flag")}需要交接的事</h2>
            <span class="sub">按超期与类型排序</span>
            <div class="right"><button class="btn sm ghost" data-go="ledger">全部台账 ${icon("arrowRight")}</button></div>
          </div>
          <div class="card-body tight">
            <div class="table-wrap">
            <table class="data stack-sm">
              <thead><tr><th>条目</th><th style="width:104px">负责人</th><th style="width:96px">截止</th><th style="width:80px">状态</th></tr></thead>
              <tbody>
                ${openItems.sort(byUrgency).slice(0, 7).map((item) => `
                  <tr data-item="${item.id}">
                    <td class="title c-title"><b>${esc(item.title)}</b>${item.detail && item.detail !== item.title ? `<small>${esc(item.detail)}</small>` : ""}</td>
                    <td class="c-who"><span class="who">${avatar(item.owner, 22)}${esc(item.owner || "无人认领")}</span></td>
                    <td class="num c-due">${item.due ? esc(fmtDate(item.due)) : "—"}<br>${dueTag(item, store.asOf)}</td>
                    <td class="c-status">${statusPill(item.status, STATUS_LABEL[item.status])}</td>
                  </tr>`).join("") || `<tr><td colspan="4">${emptyState("台账都已清空", "去收件箱录一段新的纪要", "去收件箱", "ingest")}</td></tr>`}
              </tbody>
            </table>
            </div>
          </div>
        </section>

        <div style="display:flex;flex-direction:column;gap:14px;min-width:0">
          ${section("状态构成", `${stats.total} 条`, `<div class="card-body">${donut(statusSegments(store.items), { centerValue: stats.total, centerLabel: "台账条目" })}</div>`, "", "dot")}
          ${section("类型分布", "决定 / 行动 / 风险 / 待确认", `<div class="card-body tight">${kindBars(store.items)}</div>`, "", "layers")}
        </div>
      </div>

      <div class="grid-2 even">
        ${section("到期时间轴", "点圆点打开条目", `
          <div class="card-body center">${dueTimeline(openItems, store.asOf)}</div>`, "", "calendar")}

        ${section("上手进度", `${prog.done}/${prog.total} 步`, `
          <div class="card-body">
            <div class="todo-list">
              ${MILESTONES.map((row) => {
                const done = Boolean(store.state.milestones?.[row.key]);
                return `
                  <div class="todo ${done ? "done" : ""}">
                    <span class="td-ic">${icon(done ? "check" : row.ic)}</span>
                    <span><b>${esc(row.title)}</b><small>${esc(row.hint)}</small></span>
                    <button class="btn sm ${done ? "ghost" : ""}" type="button" data-go="${row.view}">${done ? "再看一眼" : "去做"}</button>
                  </div>`;
              }).join("")}
            </div>
          </div>`, `<button class="btn sm ghost" id="overviewTour" type="button">${icon("play")} 引导</button>`, "compass")}
      </div>

      <div class="grid-2 even">
        ${section(`未关闭风险 ${risks.length}`, "交接前先看", `
          <div class="card-body tight">
            <div class="mini-list">
              ${risks.slice(0, 6).map((item) => `
                <button class="mini-item" data-item="${item.id}" type="button">
                  ${kindPill(item.kind, KIND_LABEL[item.kind])}
                  <b>${esc(item.title)}</b>
                  <span>${statusPill(item.status, STATUS_LABEL[item.status])}</span>
                </button>`).join("") || emptyState("没有未关闭的风险", "保持住", "", "", "shield")}
            </div>
          </div>`, "", "alert")}

        ${section("最近动作", "本机操作留痕", `
          <div class="card-body tight">
            <ul class="feed">
              ${active.map((entry) => `<li><time>${fmtTime(entry.at)}</time>${icon(feedIcon(entry.text))}<span>${esc(entry.text)}</span></li>`).join("")}
            </ul>
          </div>`, "", "route")}
      </div>
    `;
  },

  mount(root) {
    $("#heroTour", root)?.addEventListener("click", () => startTour(0));
    $("#overviewTour", root)?.addEventListener("click", () => startTour(0));
  },
};

function feedIcon(text) {
  if (/删除/.test(text)) return "trash";
  if (/撤销/.test(text)) return "undo";
  if (/交接/.test(text)) return "handoff";
  if (/写入|合并/.test(text)) return "merge";
  if (/新增|创建/.test(text)) return "plus";
  if (/视图/.test(text)) return "bookmark";
  if (/顺序/.test(text)) return "drag";
  if (/载入/.test(text)) return "database";
  return "edit";
}

/* ================================================================== */
/* 收件箱                                                              */
/* ================================================================== */

const ingest = {
  source: "meeting-01",
  text: "",
  candidates: [],
  result: null,
};

export const inbox = {
  title: "收件箱",
  sub: () => "粘贴纪要 → 抽取条目 → 和台账比对 → 写入",

  render() {
    const meetings = store.seed.meetings;
    const source = ingest.source;
    const meeting = meetings.find((row) => row.id === source);
    if (ingest.text === "" && meeting) ingest.text = meeting.text;

    return `
      ${howto("<b>第一步</b>：选一份纪要（或粘贴自己的），点「抽取条目」；右边逐条给出合并 / 新增判定，勾选后写入台账。", "看台账结果", "ledger", `<button class="btn sm ghost" type="button" id="ingestTour">${icon("play")} 这一步怎么做</button>`)}
      <div class="split">
        <div style="display:flex;flex-direction:column;gap:14px;min-width:0">
          <section class="card">
            <div class="card-head">
              <h2>${icon("file")}来源纪要</h2>
              <div class="right"><button class="btn sm ghost" id="ingestClear">${icon("x")} 清空</button></div>
            </div>
            <div class="card-body" style="display:flex;flex-direction:column;gap:12px">
              <div class="source-tabs" id="ingestSources">
                ${meetings.map((row) => `
                  <button type="button" data-source="${row.id}" class="${row.id === source ? "active" : ""}">${icon("file")}${esc(row.name.replace(".md", ""))}</button>`).join("")}
                <button type="button" data-source="custom" class="${source === "custom" ? "active" : ""}">${icon("edit")}自定义粘贴</button>
              </div>
              <div class="field">
                <textarea class="textarea" id="ingestText" spellcheck="false" placeholder="把会议纪要或聊天记录原文贴在这里">${esc(ingest.text)}</textarea>
                <small id="ingestMeta">${meeting ? `识别到会议日期 ${esc(meetingDateOf(ingest.text))}，共 ${ingest.text.length} 字` : `共 ${ingest.text.length} 字`}</small>
              </div>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <button class="btn primary" id="ingestRun" type="button">
                  ${icon("zap")} 抽取条目
                </button>
                <span class="tag">${icon("merge")} ${store.threshold.toFixed(2)} 判重阈值</span>
              </div>
            </div>
          </section>

          <div class="pipeline">
            <div class="${ingest.candidates.length || ingest.result ? "live-step" : ""}"><span>1</span><i class="pl-ic">${icon("file")}</i><b>读纪要</b><small>识别日期与参与人</small></div>
            <div class="${ingest.candidates.length || ingest.result ? "live-step" : ""}"><span>2</span><i class="pl-ic">${icon("zap")}</i><b>抽条目</b><small>本地规则引擎</small></div>
            <div class="${ingest.candidates.length ? "live-step" : ""}"><span>3</span><i class="pl-ic">${icon("merge")}</i><b>判重</b><small>余弦距离 ≤ ${store.threshold.toFixed(2)}</small></div>
            <div class="${ingest.result ? "live-step" : ""}"><span>4</span><i class="pl-ic">${icon("ledger")}</i><b>写台账</b><small>新增或合并历史条目</small></div>
          </div>
        </div>

        <section class="card" id="ingestResult">
          ${renderCandidates()}
        </section>
      </div>`;
  },

  mount(root) {
    $("#ingestTour", root)?.addEventListener("click", () => startTour(1));
    $("#ingestSources", root).addEventListener("click", (event) => {
      const button = event.target.closest("[data-source]");
      if (!button) return;
      ingest.source = button.dataset.source;
      const meeting = store.seed.meetings.find((row) => row.id === ingest.source);
      ingest.text = meeting ? meeting.text : "";
      ingest.candidates = [];
      ingest.result = null;
      refresh();
    });

    const area = $("#ingestText", root);
    area.addEventListener("input", () => {
      ingest.text = area.value;
      const meta = $("#ingestMeta", root);
      if (meta) meta.textContent = `共 ${area.value.length} 字`;
      ingest.source = "custom";
      $$("#ingestSources button", root).forEach((b) => b.classList.toggle("active", b.dataset.source === "custom"));
    });

    $("#ingestClear", root).addEventListener("click", () => {
      ingest.text = "";
      ingest.candidates = [];
      ingest.result = null;
      refresh();
    });

    $("#ingestRun", root).addEventListener("click", () => {
      const text = ingest.text.trim();
      if (!text) { toast("先贴一段纪要"); return; }
      ingest.result = null;
      const source = ingest.source === "custom" ? "粘贴录入" : `${ingest.source}.md`;
      ingest.candidates = extractMeeting(text, { year: 2026 }).map((candidate) => {
        const verdict = store.judge(candidate);
        return {
          ...candidate,
          source,
          distance: verdict.distance,
          matchedId: verdict.id,
          matchedTitle: verdict.title,
          merge: verdict.isDuplicate,
          picked: true,
        };
      });
      if (!ingest.candidates.length) toast("没有抽到可交代的事项，检查一下文本格式");
      else { store.mark("extract"); document.dispatchEvent(new CustomEvent("relay:progress")); }
      refresh();
    });

    const panel = $("#ingestResult", root);
    panel.addEventListener("click", (event) => {
      const bulk = event.target.closest("[data-bulk]");
      if (bulk) {
        const mode = bulk.dataset.bulk;
        ingest.candidates.forEach((candidate) => {
          candidate.picked = mode === "all" ? true
            : mode === "none" ? false
            : mode === "new" ? !candidate.merge
            : candidate.merge;
        });
        panel.innerHTML = renderCandidates();
        return;
      }
      const toggle = event.target.closest("[data-toggle]");
      if (toggle) {
        const candidate = ingest.candidates[Number(toggle.dataset.toggle)];
        candidate.merge = !candidate.merge;
        panel.innerHTML = renderCandidates();
        return;
      }
      const write = event.target.closest("#ingestWrite");
      if (write) {
        const chosen = ingest.candidates.filter((candidate) => candidate.picked);
        if (!chosen.length) { toast("没有勾选任何条目"); return; }
        ingest.result = store.writeCandidates(chosen);
        ingest.candidates = [];
        toast(`写入完成：新增 ${ingest.result.added} 条，合并 ${ingest.result.merged} 条`);
        refresh();
      }
    });

    panel.addEventListener("change", (event) => {
      const pick = event.target.closest("[data-pick]");
      if (!pick) return;
      ingest.candidates[Number(pick.dataset.pick)].picked = pick.checked;
      panel.innerHTML = renderCandidates();
    });
  },
};

function meetingDateOf(text) {
  const match = String(text).match(/时间[:：]\s*(20\d{2})-(\d{1,2})-(\d{1,2})/);
  return match ? `${match[1]}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")}` : "未知";
}

function renderCandidates() {
  if (ingest.result) {
    const { added, merged } = ingest.result;
    return `
      <div class="result-head"><h2>${icon("checkCircle")}已写入台账</h2></div>
      <div class="card-body">
        <div class="banner ok">
          ${icon("checkCircle")}
          <span>新增 <b>${added}</b> 条，合并 <b>${merged}</b> 条。台账现在共 ${store.items.length} 条。</span>
        </div>
        <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">
          <button class="btn primary" data-go="ledger" type="button">${icon("ledger")} 去台账看结果</button>
          <button class="btn" data-go="reconcile" type="button">${icon("reconcile")} 重新对账</button>
        </div>
      </div>`;
  }

  if (!ingest.candidates.length) {
    return `
      <div class="result-head"><h2>${icon("merge")}抽取结果</h2><span class="sub">等待抽取</span></div>
      ${emptyState("还没有候选条目", "选一份纪要，点「抽取条目」，这里会列出每条与台账的比对结果和距离标尺。", "", "", "merge")}`;
  }

  const rows = ingest.candidates.map((candidate, index) => {
    const distance = Number.isFinite(candidate.distance) ? candidate.distance : null;
    return `
      <div class="cand">
        <input type="checkbox" ${candidate.picked ? "checked" : ""} data-pick="${index}" aria-label="写入这条">
        ${kindPill(candidate.kind, KIND_LABEL[candidate.kind])}
        <div class="t">
          <b>${esc(candidate.title)}</b>
          ${candidate.detail && candidate.detail !== candidate.title ? `<small>${esc(candidate.detail)}</small>` : ""}
        </div>
        <div class="meta">
          <span class="who">${avatar(candidate.owner, 20)}${esc(candidate.owner || "无人")}</span>
          ${candidate.due ? ` · ${esc(fmtDate(candidate.due))}` : ""}
          <br>${statusPill(candidate.status, STATUS_LABEL[candidate.status])}
        </div>
        <div class="verdict">
          <button type="button" data-toggle="${index}" title="点击切换判定：合并 / 新增">
            ${candidate.merge ? `<span class="tag unassigned">${icon("merge")} 合并</span>` : `<span class="tag ok">${icon("plus")} 新增</span>`}
          </button>
          ${distanceMeter(distance, store.threshold)}
          ${candidate.merge && candidate.matchedTitle ? `<small class="match" title="${esc(candidate.matchedTitle)}">↳ ${esc(candidate.matchedTitle)}</small>` : ""}
        </div>
      </div>`;
  }).join("");

  const dupCount = ingest.candidates.filter((candidate) => candidate.merge && candidate.picked).length;
  const picked = ingest.candidates.filter((candidate) => candidate.picked).length;
  return `
    <div class="result-head">
      <h2>${icon("merge")}抽取结果</h2>
      <span class="sub">${ingest.candidates.length} 条 · 已勾选 ${picked} · 合并 ${dupCount} · 新增 ${picked - dupCount}</span>
      <div class="right">
        <div class="cand-tools">
          <button class="chip" data-bulk="all" type="button">全选</button>
          <button class="chip" data-bulk="none" type="button">清空</button>
          <button class="chip" data-bulk="new" type="button">${icon("plus")} 只选新增</button>
          <button class="chip" data-bulk="merge" type="button">${icon("merge")} 只选合并</button>
        </div>
        <button class="btn primary sm" id="ingestWrite" type="button" ${picked ? "" : "disabled"}>${icon("save")} 写入台账</button>
      </div>
    </div>
    <div class="candidates">${rows}</div>`;
}

/* ================================================================== */
/* 台账                                                                */
/* ================================================================== */

const ledgerView = {
  q: "",
  kind: "all",
  status: "all",
  overdueOnly: false,
  unassignedOnly: false,
  sort: "urgency",
  selected: new Set(),
};

const SORTS = [
  ["urgency", "紧急度"],
  ["due", "截止日"],
  ["owner", "负责人"],
  ["kind", "类型"],
  ["manual", "手动顺序（可拖拽）"],
];

function sortItems(rows) {
  const sorted = [...rows];
  switch (ledgerView.sort) {
    case "due": return sorted.sort((a, b) => (a.due || "9999").localeCompare(b.due || "9999"));
    case "owner": return sorted.sort((a, b) => (a.owner || "zzz").localeCompare(b.owner || "zzz", "zh"));
    case "kind": return sorted.sort((a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9));
    case "manual": return sorted;
    default: return sorted.sort(byUrgency);
  }
}

function filterItems() {
  const q = ledgerView.q.trim().toLowerCase();
  const rows = store.items.filter((item) => {
    if (ledgerView.kind !== "all" && item.kind !== ledgerView.kind) return false;
    if (ledgerView.status !== "all" && item.status !== ledgerView.status) return false;
    if (ledgerView.overdueOnly && !(store.isOpen(item) && item.due && item.due < store.asOf)) return false;
    if (ledgerView.unassignedOnly && !(store.isOpen(item) && !item.owner)) return false;
    if (q) {
      const hay = `${item.title} ${item.detail} ${item.owner}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  return sortItems(rows);
}

export const ledger = {
  title: "台账",
  sub: () => `共 ${store.items.length} 条 · ${store.stats().open} 条未完成`,

  render() {
    const views = store.state.views || [];
    return `
      ${howto("<b>台账是唯一事实</b>：点任意一行打开详情抽屉，可改可删；勾选多行可批量改状态或删除（删错能撤销）；排序切到「手动顺序」还能拖拽排优先级。", "去对账", "reconcile")}
      <section class="card">
        <div class="card-head" style="flex-wrap:wrap;gap:10px">
          <div class="search" style="position:relative;flex:1 1 220px;max-width:320px">
            ${icon("search")}
            <input class="input" id="ledgerSearch" placeholder="搜标题、详情、负责人" value="${esc(ledgerView.q)}" style="padding-left:31px">
          </div>
          <div class="chips" id="ledgerKinds">
            ${[["all", "全部类型", "layers"], ...KINDS.map((kind) => [kind, KIND_LABEL[kind], KIND_ICON[kind]])].map(([value, label, ic]) => `
              <button class="chip ${ledgerView.kind === value ? "on" : ""}" data-kind="${value}" type="button">${icon(ic)}${esc(label)}</button>`).join("")}
          </div>
          <div class="spacer"></div>
          <label class="chips" style="gap:6px">
            ${icon("sort")}
            <select class="select" id="ledgerSort" style="width:auto;padding:4px 26px 4px 9px;font-size:12px">
              ${SORTS.map(([value, label]) => `<option value="${value}" ${ledgerView.sort === value ? "selected" : ""}>${esc(label)}</option>`).join("")}
            </select>
          </label>
          <button class="btn sm primary" id="ledgerNew" type="button">${icon("plus")} 新增条目</button>
          <button class="btn sm ghost" id="ledgerExport" type="button">${icon("download")} 导出 JSON</button>
        </div>
        <div class="card-head" style="border-top:0;flex-wrap:wrap;gap:10px">
          <div class="chips" id="ledgerStatus">
            ${[["all", "全部状态"], ...STATUSES.map((status) => [status, STATUS_LABEL[status]])].map(([value, label]) => `
              <button class="chip ${ledgerView.status === value ? "on" : ""}" data-status="${value}" type="button">${esc(label)}</button>`).join("")}
          </div>
          <div class="chips">
            <button class="chip warn ${ledgerView.overdueOnly ? "on" : ""}" id="ledgerOverdue" type="button">${icon("clock")} 只看超期</button>
            <button class="chip warn ${ledgerView.unassignedOnly ? "on" : ""}" id="ledgerUnassigned" type="button">${icon("userOff")} 只看无人认领</button>
          </div>
          <div class="spacer"></div>
          <span class="sub" id="ledgerCount"></span>
        </div>
        <div class="card-head" style="border-top:0;flex-wrap:wrap;gap:8px;padding-top:0">
          <span class="sub" style="display:flex;align-items:center;gap:6px">${icon("bookmark")} 保存的视图</span>
          <div class="chips" id="ledgerViews">
            ${views.length ? views.map((view) => `
              <span class="chip" data-view-id="${view.id}" role="button" tabindex="0">${esc(view.name)}
                <button class="icon-btn x" type="button" data-view-del="${view.id}" aria-label="删除视图" style="width:16px;height:16px">${icon("x")}</button>
              </span>`).join("") : `<span class="sub">还没有，调好筛选后点右边保存</span>`}
          </div>
          <div class="spacer"></div>
          <button class="btn sm ghost" id="ledgerSaveView" type="button">${icon("save")} 保存当前筛选</button>
        </div>
        <div id="ledgerBulk"></div>
        <div class="table-wrap" id="ledgerTable"></div>
      </section>`;
  },

  mount(root) {
    const table = $("#ledgerTable", root);
    const count = $("#ledgerCount", root);
    const bulk = $("#ledgerBulk", root);

    const drawBulk = () => {
      const picked = [...ledgerView.selected].filter((id) => store.items.some((item) => item.id === id));
      ledgerView.selected = new Set(picked);
      if (!picked.length) { bulk.innerHTML = ""; return; }
      bulk.innerHTML = `
        <div class="bulk-bar">
          ${icon("check")} 已选 <b>${picked.length}</b> 条
          <div class="right">
            <select class="select" id="bulkStatus">
              ${STATUSES.map((status) => `<option value="${status}">改为「${STATUS_LABEL[status]}」</option>`).join("")}
            </select>
            <button class="btn sm" id="bulkApply" type="button">${icon("check")} 应用</button>
            <button class="btn sm danger" id="bulkDelete" type="button">${icon("trash")} 删除</button>
            <button class="btn sm ghost" id="bulkClear" type="button">取消选择</button>
          </div>
        </div>`;
      $("#bulkApply", bulk).addEventListener("click", () => {
        const status = $("#bulkStatus", bulk).value;
        const changed = store.bulkStatus(picked, status);
        ledgerView.selected.clear();
        toast(changed ? `已把 ${changed} 条改为「${STATUS_LABEL[status]}」` : "状态没有变化", changed ? { label: "撤销", onClick: () => { store.undo(); toast("已撤销"); } } : null);
      });
      $("#bulkDelete", bulk).addEventListener("click", async () => {
        const ok = await confirmDialog("批量删除", `确定删除选中的 ${picked.length} 条？删除后可以在提示条里撤销。`, "删除");
        if (!ok) return;
        const removed = store.bulkRemove(picked);
        ledgerView.selected.clear();
        toast(`已删除 ${removed} 条`, { label: "撤销", onClick: () => { store.undo(); toast("已恢复"); } });
      });
      $("#bulkClear", bulk).addEventListener("click", () => { ledgerView.selected.clear(); draw(); });
    };

    const draw = () => {
      const rows = filterItems();
      count.textContent = `${rows.length} / ${store.items.length} 条`;
      const manual = ledgerView.sort === "manual";
      const allPicked = rows.length > 0 && rows.every((item) => ledgerView.selected.has(item.id));
      table.innerHTML = `
        <table class="data stack-sm">
          <thead><tr>
            <th style="width:34px"><input type="checkbox" id="ledgerPickAll" ${allPicked ? "checked" : ""} aria-label="全选当前结果"></th>
            ${manual ? `<th style="width:30px"></th>` : ""}
            <th style="width:78px">类型</th><th>条目</th><th style="width:92px">负责人</th><th style="width:96px">截止</th><th style="width:96px">状态</th><th style="width:112px">标记</th>
          </tr></thead>
          <tbody>
            ${rows.map((item) => {
              const late = store.isOpen(item) && item.due && item.due < store.asOf;
              const noOwner = store.isOpen(item) && !item.owner;
              return `
                <tr data-item="${item.id}" data-row="${item.id}" ${manual ? 'draggable="true"' : ""} class="${ledgerView.selected.has(item.id) ? "picked" : ""}">
                  <td class="c-pick"><input type="checkbox" data-pick-row="${item.id}" ${ledgerView.selected.has(item.id) ? "checked" : ""} aria-label="选择这条"></td>
                  ${manual ? `<td class="c-drag"><span class="drag-handle" title="拖拽调整顺序">${icon("drag")}</span></td>` : ""}
                  <td class="c-kind">${kindPill(item.kind, KIND_LABEL[item.kind])}</td>
                  <td class="title c-title"><b>${esc(item.title)}</b>${item.detail && item.detail !== item.title ? `<small>${esc(item.detail)}</small>` : ""}</td>
                  <td class="c-who"><span class="who">${avatar(item.owner, 22)}${esc(item.owner || "无人")}</span></td>
                  <td class="num c-due">${item.due ? esc(fmtDate(item.due)) : "—"}</td>
                  <td class="c-status">
                    <select class="select" data-status-for="${item.id}" style="padding:3px 24px 3px 7px;font-size:12px">
                      ${STATUSES.map((status) => `<option value="${status}" ${status === item.status ? "selected" : ""}>${STATUS_LABEL[status]}</option>`).join("")}
                    </select>
                  </td>
                  <td class="c-tags">
                    ${late ? `<span class="tag due">${icon("clock")} 已超期</span>` : ""}
                    ${noOwner ? `<span class="tag unassigned">${icon("userOff")} 无人认领</span>` : ""}
                  </td>
                </tr>`;
            }).join("") || `<tr><td colspan="8">${emptyState("没有符合条件的条目", "换个筛选条件，或者先去收件箱录一段纪要。", "去收件箱", "ingest", "search")}</td></tr>`}
          </tbody>
        </table>`;
      drawBulk();
      if (manual) bindDrag();
    };

    const bindDrag = () => {
      let dragId = null;
      $$("tbody tr[data-row]", table).forEach((row) => {
        row.addEventListener("dragstart", (event) => {
          dragId = row.dataset.row;
          row.classList.add("dragging");
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", dragId);
        });
        row.addEventListener("dragend", () => {
          row.classList.remove("dragging");
          $$("tbody tr", table).forEach((r) => r.classList.remove("drop-before", "drop-after"));
        });
        row.addEventListener("dragover", (event) => {
          if (!dragId || row.dataset.row === dragId) return;
          event.preventDefault();
          const box = row.getBoundingClientRect();
          const after = event.clientY - box.top > box.height / 2;
          row.classList.toggle("drop-after", after);
          row.classList.toggle("drop-before", !after);
        });
        row.addEventListener("dragleave", () => row.classList.remove("drop-before", "drop-after"));
        row.addEventListener("drop", (event) => {
          event.preventDefault();
          const box = row.getBoundingClientRect();
          const after = event.clientY - box.top > box.height / 2;
          row.classList.remove("drop-before", "drop-after");
          if (dragId) store.reorder(dragId, row.dataset.row, after);
          dragId = null;
        });
      });
    };

    $("#ledgerSearch", root).addEventListener("input", (event) => {
      ledgerView.q = event.target.value;
      draw();
    });

    $("#ledgerSort", root).addEventListener("change", (event) => {
      ledgerView.sort = event.target.value;
      draw();
      if (ledgerView.sort === "manual") toast("现在可以拖拽行来排优先级");
    });

    $("#ledgerKinds", root).addEventListener("click", (event) => {
      const button = event.target.closest("[data-kind]");
      if (!button) return;
      ledgerView.kind = button.dataset.kind;
      $$("#ledgerKinds .chip", root).forEach((chip) => chip.classList.toggle("on", chip.dataset.kind === ledgerView.kind));
      draw();
    });

    $("#ledgerStatus", root).addEventListener("click", (event) => {
      const button = event.target.closest("[data-status]");
      if (!button) return;
      ledgerView.status = button.dataset.status;
      $$("#ledgerStatus .chip", root).forEach((chip) => chip.classList.toggle("on", chip.dataset.status === ledgerView.status));
      draw();
    });

    $("#ledgerOverdue", root).addEventListener("click", (event) => {
      ledgerView.overdueOnly = !ledgerView.overdueOnly;
      event.currentTarget.classList.toggle("on", ledgerView.overdueOnly);
      draw();
    });

    $("#ledgerUnassigned", root).addEventListener("click", (event) => {
      ledgerView.unassignedOnly = !ledgerView.unassignedOnly;
      event.currentTarget.classList.toggle("on", ledgerView.unassignedOnly);
      draw();
    });

    $("#ledgerViews", root).addEventListener("click", async (event) => {
      const del = event.target.closest("[data-view-del]");
      if (del) {
        event.stopPropagation();
        const view = store.state.views.find((row) => row.id === del.dataset.viewDel);
        const ok = await confirmDialog("删除视图", `删除保存的筛选「${view?.name || ""}」？台账数据不受影响。`, "删除");
        if (ok) store.removeView(del.dataset.viewDel);
        return;
      }
      const chip = event.target.closest("[data-view-id]");
      if (!chip) return;
      const view = store.state.views.find((row) => row.id === chip.dataset.viewId);
      if (!view) return;
      Object.assign(ledgerView, view.filters);
      ledgerView.selected = new Set();
      refresh();
      toast(`已套用视图「${view.name}」`);
    });

    $("#ledgerSaveView", root).addEventListener("click", () => {
      const suggested = [
        ledgerView.kind !== "all" ? KIND_LABEL[ledgerView.kind] : "",
        ledgerView.status !== "all" ? STATUS_LABEL[ledgerView.status] : "",
        ledgerView.overdueOnly ? "超期" : "",
        ledgerView.unassignedOnly ? "无人认领" : "",
        ledgerView.q ? `“${ledgerView.q}”` : "",
      ].filter(Boolean).join(" · ") || "全部条目";
      openModal("保存当前筛选", `
        <div class="field">
          <label for="viewName">${icon("bookmark")} 视图名称</label>
          <input class="input" id="viewName" value="${esc(suggested)}" maxlength="24">
          <small>保存的是筛选与排序条件，不是数据快照。之后在台账顶部一键套用。</small>
        </div>
        <div class="confirm-actions" style="margin-top:16px">
          <button class="btn" type="button" data-close-modal>取消</button>
          <button class="btn primary" type="button" id="viewSave">${icon("save")} 保存</button>
        </div>`, "", (modal) => {
        const input = $("#viewName", modal);
        input.focus();
        input.select();
        const save = () => {
          const name = input.value.trim();
          if (!name) { toast("给视图起个名字"); return; }
          store.saveView(name, {
            q: ledgerView.q, kind: ledgerView.kind, status: ledgerView.status,
            overdueOnly: ledgerView.overdueOnly, unassignedOnly: ledgerView.unassignedOnly, sort: ledgerView.sort,
          });
          closeModal();
          toast(`视图「${name}」已保存`);
        };
        $("#viewSave", modal).addEventListener("click", save);
        input.addEventListener("keydown", (event) => { if (event.key === "Enter") save(); });
      });
    });

    $("#ledgerNew", root).addEventListener("click", () => openItem(null));

    $("#ledgerExport", root).addEventListener("click", () => {
      download(`relay-ledger-${store.asOf}.json`, JSON.stringify({ project: store.state.project, asOf: store.asOf, items: store.items }, null, 2));
      toast("台账已导出");
    });

    table.addEventListener("change", (event) => {
      const select = event.target.closest("[data-status-for]");
      if (select) { store.setStatus(select.dataset.statusFor, select.value); return; }
      const pick = event.target.closest("[data-pick-row]");
      if (pick) {
        const id = pick.dataset.pickRow;
        if (pick.checked) ledgerView.selected.add(id);
        else ledgerView.selected.delete(id);
        pick.closest("tr")?.classList.toggle("picked", pick.checked);
        const rows = filterItems();
        const all = $("#ledgerPickAll", table);
        if (all) all.checked = rows.length > 0 && rows.every((item) => ledgerView.selected.has(item.id));
        drawBulk();
        return;
      }
      if (event.target.id === "ledgerPickAll") {
        const rows = filterItems();
        if (event.target.checked) rows.forEach((item) => ledgerView.selected.add(item.id));
        else rows.forEach((item) => ledgerView.selected.delete(item.id));
        draw();
      }
    });

    draw();
  },
};

/* ================================================================== */
/* 对账                                                                */
/* ================================================================== */

export const reconcile = {
  title: "对账",
  sub: () => `基准日 ${store.asOf}`,

  render() {
    const stats = store.stats();
    const overdue = store.overdue().sort((a, b) => (a.due || "").localeCompare(b.due || ""));
    const unassigned = store.unassigned();
    const questions = store.items.filter((item) => item.kind === "question" && store.isOpen(item));
    const blocked = store.items.filter((item) => item.status === "blocked");

    const open = store.items.filter((item) => store.isOpen(item));
    const blockerIds = new Set([...overdue, ...unassigned, ...blocked, ...questions].map((item) => item.id));
    const clean = open.filter((item) => !blockerIds.has(item.id));
    const ready = open.length ? clean.length / open.length : 1;

    const stat = (ic, color, bg, label, value, note) => `
      <div class="stat">
        <span class="st-ic" style="background:${bg};color:${color}">${icon(ic)}</span>
        <div><span>${esc(label)}</span><b style="color:${color}">${value}</b><small>${esc(note)}</small></div>
      </div>`;

    const list = (rows, render, emptyText) => `
      <div class="card-body tight">
        <div class="mini-list">
          ${rows.map(render).join("") || `<div class="empty" style="padding:26px 12px">${icon("checkCircle")}<b>${esc(emptyText)}</b></div>`}
        </div>
      </div>`;

    return `
      ${howto("对账回答一个问题：<b>现在交出去，接手人会踩哪些坑</b>。下面四张卡是坑的清单，点任意条目可直接改；确认后生成对账单，作为交接附件。", "去交接", "handoff")}
      <div class="stat-row">
        ${stat("clock", "var(--red)", "var(--red-soft)", "超期", stats.overdue, "过了基准日仍未完成")}
        ${stat("userOff", "var(--amber)", "var(--amber-soft)", "无人认领", stats.unassigned, "未完成且没有负责人")}
        ${stat("lock", "var(--magenta)", "#fbe9f7", "受阻", blocked.length, "卡在外部依赖")}
        ${stat("help", "var(--violet)", "var(--violet-soft)", "待确认", questions.length, "接手人需要先问清楚")}
      </div>

      <div class="grid-2 even">
        ${section(`已超期 ${overdue.length}`, "按原定日期排", list(overdue, (item) => `
          <button class="mini-item" data-item="${item.id}" type="button">
            ${kindPill(item.kind, KIND_LABEL[item.kind])}
            <b>${esc(item.title)}</b>
            <span class="tag due">${icon("clock")} 逾期 ${daysBetween(item.due, store.asOf)} 天</span>
          </button>`, "没有超期条目"), "", "clock")}
        ${section(`没人认领 ${unassigned.length}`, "未完成且无负责人", list(unassigned, (item) => `
          <button class="mini-item" data-item="${item.id}" type="button">
            ${kindPill(item.kind, KIND_LABEL[item.kind])}
            <b>${esc(item.title)}</b>
            <span>${statusPill(item.status, STATUS_LABEL[item.status])}</span>
          </button>`, "每条都有负责人"), "", "userOff")}
      </div>

      <div class="grid-2 even">
        ${section(`受阻 ${blocked.length}`, "卡在外部依赖", list(blocked, (item) => `
          <button class="mini-item" data-item="${item.id}" type="button">
            ${kindPill(item.kind, KIND_LABEL[item.kind])}
            <b>${esc(item.title)}</b>
            <span class="who">${avatar(item.owner, 20)}${esc(item.owner || "无人")}</span>
          </button>`, "没有受阻条目"), "", "lock")}
        ${section(`待确认 ${questions.length}`, "先问清楚再交接", list(questions, (item) => `
          <button class="mini-item" data-item="${item.id}" type="button">
            ${kindPill(item.kind, KIND_LABEL[item.kind])}
            <b>${esc(item.title)}</b>
            <span class="who">${avatar(item.owner, 20)}${esc(item.owner || "无人认领")}</span>
          </button>`, "没有悬而未决的问题"), "", "help")}
      </div>

      <div class="grid-2 even">
        ${section("交接就绪度", `${clean.length} / ${open.length} 条未完成事项没有硬伤`, `
          <div class="card-body" style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">
            ${gauge(ready, { label: "可直接交接", color: "#0f7a52" })}
            <div style="flex:1;min-width:200px">
              <p class="sub" style="margin:0 0 8px">未完成事项的构成（一条可能同时命中多项）</p>
              ${stacked([
                { label: "超期", value: overdue.length, color: "#d92d20" },
                { label: "无人认领", value: unassigned.length, color: "#b45309" },
                { label: "受阻", value: blocked.length, color: "#c026a3" },
                { label: "待确认", value: questions.length, color: "#7c3aed" },
                { label: "无硬伤", value: clean.length, color: "#0f7a52" },
              ], { height: 14 })}
              <ul class="donut-legend plain" style="margin-top:10px">
                ${[["超期", overdue.length, "#d92d20"], ["无人认领", unassigned.length, "#b45309"], ["受阻", blocked.length, "#c026a3"], ["待确认", questions.length, "#7c3aed"], ["无硬伤", clean.length, "#0f7a52"]]
                  .map(([label, value, color]) => `<li><i style="background:${color}"></i><span>${label}</span><b>${value}</b></li>`).join("")}
              </ul>
            </div>
          </div>`, "", "target")}
        ${section("负责人负载", `${stats.open} 条未完成`, `
          <div class="card-body tight">${ownerLoad(store.items)}</div>`, "", "users")}
      </div>

      ${section("状态矩阵", "类型 × 状态，颜色越深堆积越多", `
        <div class="table-wrap">${matrixTable()}</div>`, "", "grid")}

      ${section("对账单", "基准日快照，可直接作为交接附件", `
        <div class="card-body">
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn primary" id="reportOpen" type="button">${icon("file")} 生成对账报告</button>
            <button class="btn" id="reportCopy" type="button">${icon("copy")} 复制 Markdown</button>
            <button class="btn ghost" id="reportDownload" type="button">${icon("download")} 下载 .md</button>
          </div>
          <div class="report-preview" id="reportPreview">
            <div class="empty" style="padding:22px 0">${icon("file")}<b>点「生成对账报告」在这里预览</b>内容与下载文件完全一致</div>
          </div>
        </div>`, "", "reconcile")}
    `;
  },

  mount(root) {
    const report = () => buildReport();
    const preview = $("#reportPreview", root);
    const show = () => {
      preview.innerHTML = `<pre>${esc(report())}</pre>`;
      store.mark("reconcile");
      document.dispatchEvent(new CustomEvent("relay:progress"));
    };
    $("#reportOpen", root).addEventListener("click", () => {
      show();
      toast("对账报告已生成");
      preview.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    $("#reportCopy", root).addEventListener("click", () => {
      if (!preview.querySelector("pre")) show();
      copyText(report(), "报告已复制");
    });
    $("#reportDownload", root).addEventListener("click", () => {
      download(`relay-reconcile-${store.asOf}.md`, report());
      toast("报告已下载");
    });
  },
};

function matrixTable() {
  const total = store.items.length;
  const grid = KINDS.map((kind) => STATUSES.map((status) => store.items.filter((item) => item.kind === kind && item.status === status).length));
  const max = Math.max(1, ...grid.flat());
  const rows = KINDS.map((kind, index) => {
    const cells = grid[index];
    const sum = cells.reduce((a, b) => a + b, 0);
    return `<tr>
      <td><span class="pill ${kind}">${icon(KIND_ICON[kind])}${KIND_LABEL[kind]}</span></td>
      ${cells.map((count) => `<td class="${count >= 3 ? "hot" : ""}" style="${heatStyle(count, max)}">${count || "·"}</td>`).join("")}
      <td>${sum}</td></tr>`;
  }).join("");
  const foot = STATUSES.map((status) => store.items.filter((item) => item.status === status).length);
  return `
    <table class="matrix">
      <thead><tr><th>类型</th>${STATUSES.map((status) => `<th>${STATUS_LABEL[status]}</th>`).join("")}<th>合计</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><td>合计</td>${foot.map((count) => `<td>${count}</td>`).join("")}<td>${total}</td></tr></tfoot>
    </table>`;
}

function buildReport() {
  const stats = store.stats();
  const overdue = store.overdue().sort((a, b) => (a.due || "").localeCompare(b.due || ""));
  const unassigned = store.unassigned();
  const lines = [
    `# ${store.state.project} 登录改造 · 对账报告`,
    `基准日 ${store.asOf}｜共 ${stats.total} 条｜未完成 ${stats.open}｜已完成 ${stats.done}｜超期 ${stats.overdue}｜无人认领 ${stats.unassigned}`,
    "",
    `## 已超期（${overdue.length}）`,
    ...overdue.map((item) => `- ${item.title}｜${item.owner || "无人认领"}｜原定 ${item.due}（逾期 ${daysBetween(item.due, store.asOf)} 天）`),
    "",
    `## 没人认领（${unassigned.length}）`,
    ...unassigned.map((item) => `- ${item.title}｜${KIND_LABEL[item.kind]}`),
    "",
    "## 未完成明细",
    ...store.items
      .filter((item) => store.isOpen(item))
      .sort(byUrgency)
      .map((item) => `- [${KIND_LABEL[item.kind]}] ${item.title}｜${item.owner || "无人认领"}${item.due ? `｜原定 ${item.due}` : ""}｜${STATUS_LABEL[item.status]}`),
    "",
    "## 状态分布",
    ...STATUSES.map((status) => `- ${STATUS_LABEL[status]}：${store.items.filter((item) => item.status === status).length}`),
  ];
  return lines.join("\n");
}

/* ================================================================== */
/* 检索                                                                */
/* ================================================================== */

const retrievalState = { query: "登录接口很慢，数据库连接池打满", keyword: "连接池" };

export const retrieval = {
  title: "检索",
  sub: () => "关键词 / 语义 / 混合三路对比",

  render() {
    const docs = store.items.map((item) => `${item.title}\n${item.detail || ""}`);
    const avg = docs.length ? Math.round(docs.reduce((sum, doc) => sum + tokenize(doc).length, 0) / docs.length) : 0;
    const presets = [
      { q: "登录接口很慢，数据库连接池打满", k: "连接池", ic: "database" },
      { q: "token 不一致会怎样", k: "token", ic: "lock" },
      { q: "灰度放量到多少合适", k: "灰度", ic: "trendUp" },
      { q: "发布推迟到什么时候", k: "推迟", ic: "calendar" },
      { q: "交接前有哪些风险", k: "风险", ic: "alert" },
    ];
    return `
      ${howto("同一句话，三种找法：<b>关键词</b>只认字面，<b>语义</b>认意思，<b>混合 RRF</b> 把两路排名融合。改上面的输入，三列实时重排——点结果可直接打开条目。", "回台账", "ledger")}
      <section class="card">
        <div class="card-head"><h2>${icon("search")} 查询</h2><span class="sub">对当前台账 ${store.items.length} 条检索</span></div>
        <div class="card-body">
          <div class="query-grid">
            <div class="field">
              <label for="qSemantic">${icon("message")} 想查的事（自然语言）</label>
              <input class="input" id="qSemantic" value="${esc(retrievalState.query)}" placeholder="用一句话描述你要找的事">
            </div>
            <div class="field">
              <label for="qKeyword">${icon("target")} 关键词（全文匹配）</label>
              <input class="input" id="qKeyword" value="${esc(retrievalState.keyword)}" placeholder="精确词">
            </div>
          </div>
          <div class="presets" id="retrievalPresets">
            ${presets.map((preset) => `<button type="button" data-q="${esc(preset.q)}" data-k="${esc(preset.k)}">${icon(preset.ic)}${esc(preset.q)}</button>`).join("")}
          </div>
        </div>
      </section>

      <div class="index-strip">
        <div><span class="is-ic">${icon("database")}</span><span><span>台账文档</span><b>${store.items.length}</b></span></div>
        <div><span class="is-ic" style="background:var(--blue-soft);color:var(--blue)">${icon("layers")}</span><span><span>词表</span><b>${store.vectorizer.idf.size}</b></span></div>
        <div><span class="is-ic" style="background:var(--violet-soft);color:var(--violet)">${icon("split")}</span><span><span>平均词元</span><b>${avg}</b></span></div>
        <div><span class="is-ic" style="background:var(--relay-soft);color:var(--relay-deep)">${icon("merge")}</span><span><span>合并阈值</span><b>${store.threshold.toFixed(2)}</b></span></div>
      </div>

      <div id="retrievalCols"></div>
      <div id="retrievalExplain"></div>
    `;
  },

  mount(root) {
    const cols = $("#retrievalCols", root);
    const explain = $("#retrievalExplain", root);
    let timer = null;

    const draw = () => {
      const result = runSearch(store, retrievalState.query, retrievalState.keyword);
      const items = new Map(store.items.map((item) => [item.id, item]));
      const keywordMax = Math.max(1, ...result.keywordRanking.slice(0, 6).map((id) => {
        const item = items.get(id);
        return countKeyword(`${item.title}\n${item.detail || ""}`, retrievalState.keyword);
      }));
      const semanticMax = Math.max(0.0001, ...result.semanticRanking.slice(0, 6).map((id) => result.semanticScore.get(id) || 0));
      const rrfMax = Math.max(0.0001, ...result.hybrid.slice(0, 6).map((row) => row.score));
      cols.innerHTML = `
        <div class="cols-3">
          ${column("只关键词", "命中次数排序", result.keywordRanking.slice(0, 6), items, (id) => {
            const item = items.get(id);
            const hits = countKeyword(`${item.title}\n${item.detail || ""}`, retrievalState.keyword);
            return { text: `${hits} 次命中`, bar: scoreBar(hits, keywordMax, "#2563eb") };
          }, false, "target", "#2563eb")}
          ${column("只语义", "余弦相似度（越大越近）", result.semanticRanking.slice(0, 6), items, (id) => {
            const sim = result.semanticScore.get(id) || 0;
            return { text: sim.toFixed(4), bar: scoreBar(sim, semanticMax, "#0d7d8a") };
          }, true, "sparkles", "#0d7d8a")}
          ${column("混合 RRF", "两路排名融合 · k=60", result.hybrid.slice(0, 6).map((row) => row.id), items, (id) => {
            const row = result.hybrid.find((entry) => entry.id === id);
            const score = row?.score || 0;
            return { text: score.toFixed(4), bar: scoreBar(score, rrfMax, "#d9542b") };
          }, true, "merge", "#d9542b")}
        </div>`;

      const top = result.hybrid.slice(0, 3);
      const tokens = [...new Set(tokenize(retrievalState.query))];
      explain.innerHTML = `
        <section class="card">
          <div class="card-head"><h2>${icon("info")} 排序解释</h2><span class="sub">混合结果前三名的分数构成</span></div>
          <div class="card-body">
            <p class="sub" style="margin:0">查询被切成的词元（中文二元组 + 英文/数字词）</p>
            <div class="tokens">${tokens.map((token) => `<code>${esc(token)}</code>`).join("") || `<span class="sub">查询为空</span>`}</div>
            <div class="table-wrap" style="margin-top:12px">
              <table class="explain-table">
                <thead><tr><th>名次</th><th>条目</th><th>关键词命中</th><th>语义相似度</th><th>RRF</th></tr></thead>
                <tbody>
                  ${top.map((row, index) => {
                    const item = items.get(row.id);
                    if (!item) return "";
                    const hits = countKeyword(`${item.title}\n${item.detail || ""}`, retrievalState.keyword);
                    const keywordRank = result.keywordRanking.indexOf(row.id);
                    const semanticRank = result.semanticRanking.indexOf(row.id);
                    return `
                      <tr class="${index === 0 ? "top" : ""}">
                        <td>${index + 1}</td>
                        <td>${esc(item.title)}<div class="muted" style="font-size:11px">关键词第 ${keywordRank < 0 ? "—" : keywordRank + 1} 名 · 语义第 ${semanticRank < 0 ? "—" : semanticRank + 1} 名</div></td>
                        <td>${hits}</td>
                        <td>${(result.semanticScore.get(row.id) || 0).toFixed(4)}</td>
                        <td>${row.score.toFixed(4)}</td>
                      </tr>`;
                  }).join("")}
                </tbody>
              </table>
            </div>
          </div>
        </section>`;
    };

    const onInput = (event) => {
      if (event.target.id === "qSemantic") retrievalState.query = event.target.value;
      if (event.target.id === "qKeyword") retrievalState.keyword = event.target.value;
      clearTimeout(timer);
      timer = setTimeout(draw, 160);
    };
    $("#qSemantic", root).addEventListener("input", onInput);
    $("#qKeyword", root).addEventListener("input", onInput);
    $("#retrievalPresets", root).addEventListener("click", (event) => {
      const button = event.target.closest("[data-q]");
      if (!button) return;
      retrievalState.query = button.dataset.q;
      retrievalState.keyword = button.dataset.k || "";
      $("#qSemantic", root).value = retrievalState.query;
      $("#qKeyword", root).value = retrievalState.keyword;
      draw();
    });
    draw();
  },
};

function countKeyword(text, keyword) {
  if (!keyword) return 0;
  let count = 0;
  let index = text.indexOf(keyword);
  while (index !== -1) { count += 1; index = text.indexOf(keyword, index + keyword.length); }
  return count;
}

function column(title, sub, ids, items, scoreOf, highlight = false, ic = "search", color = "#0d7d8a") {
  return `
    <section class="card">
      <div class="card-head"><h2>${icon(ic)} ${esc(title)}</h2><span class="sub">${esc(sub)}</span></div>
      <div class="card-body" style="padding-top:6px;padding-bottom:6px">
        ${ids.length ? `<div class="rank-list">${ids.map((id, index) => {
          const item = items.get(id);
          if (!item) return "";
          const score = scoreOf(id);
          const text = typeof score === "string" ? score : score.text;
          const bar = typeof score === "string" ? "" : score.bar;
          return `
            <div class="rank" data-item="${item.id}" style="cursor:pointer">
              <span class="no" ${index === 0 ? `style="background:${color};color:#fff"` : ""}>${index + 1}</span>
              <span><b>${esc(item.title)}</b><small>${icon(KIND_ICON[item.kind])} ${KIND_LABEL[item.kind]} · ${esc(item.owner || "无人认领")}</small></span>
              <span class="score ${highlight ? "hi" : ""}">${esc(text)}${bar}</span>
            </div>`;
        }).join("")}</div>` : `<div class="empty" style="padding:26px 12px">${icon("search")}<b>没有命中</b>换个说法或关键词试试</div>`}
      </div>
    </section>`;
}

/* ================================================================== */
/* 交接                                                                */
/* ================================================================== */

const handoffState = {
  objective: "把登录接口 P95 从 1.2s 降到 400ms 以内，灰度验证后全量发布",
  from: "张伟",
  to: "赵磊",
  checks: { live_state: false, capability: false, authorization: false },
};

export const handoff = {
  title: "交接",
  sub: () => `${handoffState.from} → ${handoffState.to}`,

  render() {
    const card = buildCard();
    return `
      ${howto("交接不是把清单甩过去：<b>交出的人</b>写目标，<b>接手的人</b>逐项核对实时状态、能力与授权，三项都确认才能生成。右侧交接卡随台账实时更新，可复制成 Markdown 发给对方。", "看对账", "reconcile")}
      <div class="split wide-right">
        <div style="display:flex;flex-direction:column;gap:14px;min-width:0">
          <section class="card">
            <div class="card-head"><h2>${icon("route")} 交接信息</h2></div>
            <div class="card-body" style="display:flex;flex-direction:column;gap:12px">
              <div class="field">
                <label for="hoObjective">${icon("target")} 项目目标</label>
                <textarea class="textarea" id="hoObjective" style="min-height:64px">${esc(handoffState.objective)}</textarea>
              </div>
              <div class="meta-grid">
                <div class="field"><label for="hoFrom">${icon("arrowUpRight")} 交出的人</label><input class="input" id="hoFrom" value="${esc(handoffState.from)}"></div>
                <div class="field"><label for="hoTo">${icon("user")} 接手的人</label><input class="input" id="hoTo" value="${esc(handoffState.to)}"></div>
              </div>
              <div class="pair" id="hoPair">${pairHtml()}</div>
            </div>
          </section>

          <section class="card">
            <div class="card-head"><h2>${icon("check")} 接手人核对</h2><span class="sub">三项都确认才能生成</span></div>
            <div class="card-body tight">
              <div class="check-meter" style="padding:0 12px 10px">
                <span id="hoCheckCount">0 / 3</span>
                <span class="cm-track"><i id="hoCheckBar" style="width:0%"></i></span>
              </div>
              <div class="check-list" id="hoChecks">
                ${checkRow("live_state", "看过实时台账", "确认清单来自当前状态，不是会议印象", "eye")}
                ${checkRow("capability", "能力对得上", "接手人有时间与权限处理这些待办", "users")}
                ${checkRow("authorization", "授权已确认", "可以改动灰度配置与线上接口", "shield")}
              </div>
            </div>
          </section>

          <button class="btn primary" id="hoRun" type="button" style="justify-content:center;padding:11px">
            ${icon("handoff")} 生成交接（契约 → 交接 → 回执 → 结果）
          </button>
        </div>

        <div style="min-width:0;display:flex;flex-direction:column;gap:14px">
          ${card}
          ${section(`交接记录 ${store.state.handoffs.length}`, "本机保存，点开可复制", `
            <div class="card-body tight">
              ${store.state.handoffs.length ? `<div class="mini-list">${store.state.handoffs.map((record) => `
                <button class="mini-item" data-handoff="${record.id}" type="button">
                  ${avatar(record.from, 22)}
                  <b>${esc(record.from)} → ${esc(record.to)}</b>
                  <span class="sub" style="margin-left:auto;font-size:11.5px;color:var(--ink-4)">${icon("clock")} ${fmtStmt(record.at)}</span>
                </button>`).join("")}</div>` : `<div class="empty" style="padding:26px 12px">${icon("handoff")}<b>还没有生成过交接</b>左侧三项核对后点生成</div>`}
            </div>`, "", "layers")}
        </div>
      </div>`;
  },

  mount(root) {
    const refreshCard = () => {
      $("#handoffCard", root).outerHTML = buildCard();
      $("#hoPair", root).innerHTML = pairHtml();
      $("#viewSub").textContent = handoff.sub();
    };

    $("#hoObjective", root).addEventListener("input", (event) => {
      handoffState.objective = event.target.value;
      $("#handoffCard", root).outerHTML = buildCard();
    });
    $("#hoFrom", root).addEventListener("input", (event) => {
      handoffState.from = event.target.value;
      refreshCard();
    });
    $("#hoTo", root).addEventListener("input", (event) => {
      handoffState.to = event.target.value;
      refreshCard();
    });

    $("#hoChecks", root).addEventListener("change", (event) => {
      const box = event.target.closest("[data-check]");
      if (!box) return;
      handoffState.checks[box.dataset.check] = box.checked;
      box.closest(".check").classList.toggle("on", box.checked);
      updateRunState(root);
    });

    $("#hoRun", root).addEventListener("click", () => {
      const record = createHandoff();
      handoffState.checks = { live_state: false, capability: false, authorization: false };
      store.addHandoff(record);
      toast("交接已生成，记录在右侧列表");
      showHandoff(record);
    });

    root.addEventListener("click", (event) => {
      const button = event.target.closest("[data-handoff]");
      if (!button) return;
      const record = store.state.handoffs.find((row) => row.id === button.dataset.handoff);
      if (record) showHandoff(record);
    });

    updateRunState(root);
  },
};

function pairHtml() {
  return `
    ${avatar(handoffState.from, 30)}
    <span class="pair-arrow">${icon("arrowRight")}</span>
    ${avatar(handoffState.to, 30)}
    <span class="sub" style="margin-left:4px">${esc(handoffState.from || "—")} 把 ${store.stats().open} 条未完成事项交给 ${esc(handoffState.to || "—")}</span>`;
}

const CHECK_ICON = { live_state: "eye", capability: "users", authorization: "shield" };

function checkRow(key, title, sub, ic) {
  return `
    <label class="check ${handoffState.checks[key] ? "on" : ""}">
      <input type="checkbox" data-check="${key}" ${handoffState.checks[key] ? "checked" : ""}>
      <span class="ck-ic">${icon(ic || CHECK_ICON[key] || "check")}</span>
      <span><b>${esc(title)}</b><small>${esc(sub)}</small></span>
    </label>`;
}

function updateRunState(root) {
  const button = $("#hoRun", root);
  if (!button) return;
  const done = Object.values(handoffState.checks).filter(Boolean).length;
  const ready = done === 3;
  button.disabled = !ready;
  const count = $("#hoCheckCount", root);
  const bar = $("#hoCheckBar", root);
  if (count) count.textContent = `${done} / 3`;
  if (bar) bar.style.width = `${(done / 3) * 100}%`;
}

const SECTION_META = {
  overdue: { ic: "clock", cls: "s-overdue" },
  unassigned: { ic: "userOff", cls: "s-unassigned" },
  open: { ic: "zap", cls: "s-open" },
  done: { ic: "checkCircle", cls: "s-done" },
  decisions: { ic: "shield", cls: "s-decisions" },
  risks: { ic: "alert", cls: "s-risks" },
  questions: { ic: "help", cls: "s-questions" },
};

function buildCard() {
  const sections = cardSections();
  return `
    <article class="handoff-card" id="handoffCard">
      <header>
        <h2>${icon("baton")} ${esc(store.state.project)} · 交接卡</h2>
        <p>${icon("calendar")} 截至 ${esc(store.asOf)}<span class="pair-inline">${avatar(handoffState.from, 20)} ${esc(handoffState.from || "—")} ${icon("arrowRight")} ${avatar(handoffState.to, 20)} ${esc(handoffState.to || "—")}</span></p>
      </header>
      <div class="handoff-sec">
        <h3>${icon("target")} 目标</h3>
        <p style="margin:0;font-size:13px;color:var(--ink-2)">${esc(handoffState.objective || "（填写项目目标）")}</p>
      </div>
      ${Object.keys(SECTION_META).map((key) => {
        const group = sections[key];
        if (!group.items.length) return "";
        const meta = SECTION_META[key];
        return `
          <div class="handoff-sec ${meta.cls}">
            <h3>${icon(meta.ic)} ${esc(group.title)}<span>${group.items.length}</span></h3>
            <ul>${group.items.map((line) => `<li>${line}</li>`).join("")}</ul>
          </div>`;
      }).join("")}
    </article>`;
}

function cardSections() {
  const open = store.items.filter((item) => store.isOpen(item)).sort(byUrgency);
  const overdue = store.overdue().sort((a, b) => (a.due || "").localeCompare(b.due || ""));
  const unassigned = store.unassigned();
  const done = store.items.filter((item) => item.status === "done");
  const decisions = store.items.filter((item) => item.kind === "decision");
  const risks = store.items.filter((item) => item.kind === "risk" && item.status !== "done");
  const questions = store.items.filter((item) => item.kind === "question" && store.isOpen(item));

  const label = (item) => `<b>${esc(item.title)}</b>｜${avatar(item.owner, 18)}${esc(item.owner || "无人认领")}${item.due ? `｜原定 ${esc(fmtDate(item.due))}` : ""}`;
  const seen = new Set([...overdue, ...unassigned].map((item) => item.id));
  const rest = open.filter((item) => !seen.has(item.id));

  return {
    overdue: { title: "已超期", items: overdue.map(label) },
    unassigned: { title: "没人认领", items: unassigned.map((item) => esc(item.title)) },
    open: { title: "其余未完成", items: rest.map(label) },
    done: { title: "已完成", items: done.map((item) => `<b>${esc(item.title)}</b>｜${esc(item.owner || "无人认领")}`) },
    decisions: { title: "生效中的决定与约束", items: decisions.map((item) => `<b>${esc(item.title)}</b>：${esc((item.detail || "").slice(0, 60))}`) },
    risks: { title: "风险", items: risks.map(label) },
    questions: { title: "还没确认的问题", items: questions.map(label) },
  };
}

function createHandoff() {
  const clock = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  const now = new Date(`${store.asOf}T${pad(clock.getHours())}:${pad(clock.getMinutes())}:${pad(clock.getSeconds())}`);
  const sections = cardSections();
  const openCount = store.items.filter((item) => store.isOpen(item)).length;
  const steps = [
    { name: "工作契约", detail: `in_scope ${openCount} 项`, at: now.toISOString() },
    { name: "Prepared Handoff", detail: `state ${openCount} 项`, at: new Date(now.getTime() + 800).toISOString() },
    { name: "接手回执", detail: `checks 3/3 confirmed`, at: new Date(now.getTime() + 1600).toISOString() },
    { name: "任务结果", detail: `open ${openCount} 项`, at: new Date(now.getTime() + 2400).toISOString() },
  ].map((step) => ({ ...step, position: store.nextPosition() }));

  return {
    id: `ho_${Math.random().toString(36).slice(2, 8)}`,
    at: now.toISOString(),
    from: handoffState.from || "—",
    to: handoffState.to || "—",
    objective: handoffState.objective,
    asOf: store.asOf,
    sections,
    steps,
    checks: { ...handoffState.checks },
  };
}

function handoffMarkdown(record) {
  const lines = [
    `# ${store.state.project} · 交接卡`,
    `截至 ${record.asOf}｜${record.from} → ${record.to}`,
    "",
    "## 目标",
    record.objective || "（未填写）",
    "",
  ];
  for (const key of ["overdue", "unassigned", "open", "done", "decisions", "risks", "questions"]) {
    const group = record.sections[key];
    if (!group.items.length) continue;
    lines.push(`## ${group.title}（${group.items.length}）`);
    lines.push(...group.items.map((item) => `- ${item.replace(/<span class="avatar-c"[^>]*>.*?<\/span>/g, "").replace(/<[^>]+>/g, "")}`));
    lines.push("");
  }
  lines.push("## 交接步骤");
  lines.push(...record.steps.map((step) => `- ${step.name}｜position=${step.position}｜${step.detail}`));
  return lines.join("\n");
}

const STEP_ICON = ["file", "handoff", "check", "flag"];

function showHandoff(record) {
  const body = `
    <div class="steps">
      ${record.steps.map((step, index) => `
        <div class="step done">
          <span class="idx">${icon(STEP_ICON[index] || "check")}</span>
          <span><b>${esc(step.name)}</b><small>position=${step.position} · ${esc(step.detail)}</small></span>
          <em>${fmtTime(step.at)}</em>
        </div>`).join("")}
    </div>
    <div class="ho-summary">
      <span>${icon("calendar")} 截至 ${esc(record.asOf)}</span>
      <span>${icon("layers")} 清单 ${Object.values(record.sections).reduce((sum, group) => sum + group.items.length, 0)} 行</span>
      <span>${icon("check")} 核对 3/3</span>
    </div>
    <div style="margin-top:14px">
      <pre>${esc(handoffMarkdown(record))}</pre>
    </div>`;
  openModal(
    `${record.from} → ${record.to}｜${fmtStmt(record.at)}`,
    body,
    `<button class="btn sm" data-copy type="button">${icon("copy")} 复制</button>
     <button class="btn sm ghost" data-download type="button">${icon("download")} 下载</button>`,
    (modal) => {
      $("[data-copy]", modal).addEventListener("click", () => copyText(handoffMarkdown(record), "交接卡已复制"));
      $("[data-download]", modal).addEventListener("click", () => {
        download(`relay-handoff-${record.asOf}.md`, handoffMarkdown(record));
        toast("交接卡已下载");
      });
    },
  );
}

/* ================================================================== */
/* 条目抽屉（台账、检索、概览共用）                                      */
/* ================================================================== */

export function openItem(id) {
  const item = id ? store.items.find((row) => row.id === id) : null;
  const editing = Boolean(item);
  const draft = item
    ? { ...item }
    : { kind: "action", title: "", detail: "", owner: "", due: "", status: "open" };

  const html = `
    <div class="drawer-head">
      <h2>${icon(editing ? "edit" : "plus")} ${editing ? "编辑条目" : "新增条目"}</h2>
      <div class="right">
        ${editing ? `<button class="btn sm danger" data-delete type="button">${icon("trash")} 删除</button>` : ""}
        <button class="icon-btn" data-close type="button" aria-label="关闭">${icon("x")}</button>
      </div>
    </div>
    <div class="drawer-body">
      ${editing ? `<div class="drawer-tags">${kindPill(draft.kind, KIND_LABEL[draft.kind])}${statusPill(draft.status, STATUS_LABEL[draft.status])}${dueTag(draft, store.asOf)}</div>` : ""}
      <div class="field">
        <label>${icon("layers")} 类型</label>
        <div class="chips" data-kind-picker>
          ${KINDS.map((kind) => `<button type="button" class="chip ${draft.kind === kind ? "on" : ""}" data-kind-pick="${kind}">${icon(KIND_ICON[kind])}${KIND_LABEL[kind]}</button>`).join("")}
        </div>
        <select class="select" data-field="kind" style="display:none">
          ${KINDS.map((kind) => `<option value="${kind}" ${draft.kind === kind ? "selected" : ""}>${KIND_LABEL[kind]}</option>`).join("")}
        </select>
      </div>
      <div class="field"><label>${icon("edit")} 标题</label><input class="input" data-field="title" value="${esc(draft.title)}" placeholder="一句话说清这件事"></div>
      <div class="field"><label>${icon("file")} 详情</label><textarea class="textarea" data-field="detail" style="min-height:110px">${esc(draft.detail || "")}</textarea></div>
      <div class="meta-grid">
        <div class="field"><label>${icon("user")} 负责人</label><input class="input" data-field="owner" value="${esc(draft.owner || "")}" placeholder="留空 = 无人认领"></div>
        <div class="field"><label>${icon("calendar")} 截止</label><input class="input" type="date" data-field="due" value="${esc(draft.due || "")}"></div>
      </div>
      <div class="field">
        <label>${icon("flag")} 状态</label>
        <select class="select" data-field="status">
          ${STATUSES.map((status) => `<option value="${status}" ${draft.status === status ? "selected" : ""}>${STATUS_LABEL[status]}</option>`).join("")}
        </select>
      </div>
      ${editing ? `<div class="field"><label>${icon("link")} 来源</label><pre>${esc(draft.source || "—")}\nid: ${esc(draft.id)}</pre></div>` : ""}
    </div>
    <div class="drawer-foot">
      <button class="btn ghost" data-close type="button">取消</button>
      <button class="btn primary" data-save type="button">${icon("save")} ${editing ? "保存修改" : "创建条目"}</button>
    </div>`;

  openDrawer(html, (drawer) => {
    const read = () => {
      const patch = {};
      $$("[data-field]", drawer).forEach((field) => { patch[field.dataset.field] = field.value.trim(); });
      return patch;
    };
    $$("[data-close]", drawer).forEach((button) => button.addEventListener("click", closeDrawer));
    $("[data-kind-picker]", drawer).addEventListener("click", (event) => {
      const button = event.target.closest("[data-kind-pick]");
      if (!button) return;
      $("[data-field='kind']", drawer).value = button.dataset.kindPick;
      $$("[data-kind-pick]", drawer).forEach((chip) => chip.classList.toggle("on", chip === button));
    });
    const save = $("[data-save]", drawer);
    save.addEventListener("click", () => {
      const patch = read();
      if (!patch.title) { toast("标题不能为空"); return; }
      if (editing) store.updateItem(item.id, patch);
      else store.addItem(patch);
      closeDrawer();
      toast(editing ? "已保存" : "条目已创建");
    });
    const del = $("[data-delete]", drawer);
    if (del) {
      del.addEventListener("click", async () => {
        const ok = await confirmDialog("删除条目", `确定删除「${item.title}」？删除后可以在提示条里撤销。`, "删除");
        if (!ok) return;
        store.removeItem(item.id);
        closeDrawer();
        toast("已删除", { label: "撤销", onClick: () => { store.undo(); toast("已恢复"); } });
      });
    }
    setTimeout(() => $("[data-field='title']", drawer)?.focus(), 60);
  });
}
