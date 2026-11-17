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
  openDrawer, closeDrawer, openModal, closeModal, copyText, download,
  kindPill, statusPill,
} from "./ui.js";

const KIND_ORDER = { risk: 0, action: 1, decision: 2, question: 3 };
const STATUS_ORDER = { open: 0, blocked: 1, in_progress: 2, done: 3, stale: 4 };

const byUrgency = (a, b) => {
  const s = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
  if (s) return s;
  const d = (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9);
  if (d) return d;
  return (a.due || "9999").localeCompare(b.due || "9999");
};

const refresh = () => document.dispatchEvent(new CustomEvent("relay:rerender"));

function section(title, sub, body, right = "") {
  return `
    <section class="card">
      <div class="card-head">
        <h2>${esc(title)}</h2>
        ${sub ? `<span class="sub">${esc(sub)}</span>` : ""}
        ${right ? `<div class="right">${right}</div>` : ""}
      </div>
      ${body}
    </section>`;
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
    const key = item.owner || "无人认领";
    map.set(key, (map.get(key) || 0) + 1);
  }
  const rows = [...map.entries()].sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...rows.map((row) => row[1]));
  return `
    <div class="bars">
      ${rows.map(([owner, count]) => `
        <div class="bar-row">
          <span>${esc(owner)}</span>
          <i><u style="width:${(count / max) * 100}%"></u></i>
          <em>${count}</em>
        </div>`).join("") || `<div class="empty">没有未完成事项</div>`}
    </div>`;
}

function kindBars(items) {
  const counts = KINDS.map((kind) => [kind, items.filter((item) => item.kind === kind).length]);
  const max = Math.max(1, ...counts.map((row) => row[1]));
  return `
    <div class="bars">
      ${counts.map(([kind, count]) => `
        <div class="bar-row">
          <span>${esc(KIND_LABEL[kind])}</span>
          <i><u style="width:${(count / max) * 100}%"></u></i>
          <em>${count}</em>
        </div>`).join("")}
    </div>`;
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
    const openWithDue = store.items
      .filter((item) => store.isOpen(item) && item.due)
      .sort((a, b) => a.due.localeCompare(b.due));
    const risks = items.filter((item) => item.kind === "risk" && item.status !== "done");
    const active = store.state.activity.slice(0, 7);

    return `
      <div class="kpis">
        <div class="kpi"><span>台账条目</span><b>${stats.total}</b><small>${stats.open} 条未完成</small></div>
        <div class="kpi"><span>已完成</span><b>${stats.done}</b><small>完成率 ${stats.total ? Math.round((stats.done / stats.total) * 100) : 0}%</small></div>
        <div class="kpi ${stats.overdue ? "alert" : ""}"><span>已超期</span><b>${stats.overdue}</b><small>基准日 ${esc(store.asOf)}</small></div>
        <div class="kpi ${stats.unassigned ? "warn" : ""}"><span>无人认领</span><b>${stats.unassigned}</b><small>未完成且无负责人</small></div>
        <div class="kpi ${stats.risks ? "warn" : ""}"><span>未关闭风险</span><b>${stats.risks}</b><small>交接前必须先看</small></div>
      </div>

      <div class="grid-2">
        <section class="card">
          <div class="card-head">
            <h2>需要交接的事</h2>
            <span class="sub">按超期与类型排序</span>
            <div class="right"><button class="btn sm ghost" data-go="reconcile">打开对账</button></div>
          </div>
          <div class="card-body tight">
            <table class="data">
              <thead><tr><th>条目</th><th>负责人</th><th>截止</th><th>状态</th></tr></thead>
              <tbody>
                ${items.filter((item) => store.isOpen(item)).slice(0, 7).map((item) => `
                  <tr data-item="${item.id}">
                    <td class="title"><b>${esc(item.title)}</b>${item.detail && item.detail !== item.title ? `<small>${esc(item.detail)}</small>` : ""}</td>
                    <td>${item.owner ? esc(item.owner) : `<span class="status-pill">无人认领</span>`}</td>
                    <td class="num">${item.due ? esc(fmtDate(item.due)) : "—"}<br>${dueTag(item, store.asOf)}</td>
                    <td>${statusPill(item.status, STATUS_LABEL[item.status])}</td>
                  </tr>`).join("") || `<tr><td colspan="4"><div class="empty">台账都已清空</div></td></tr>`}
              </tbody>
            </table>
          </div>
        </section>

        <div style="display:flex;flex-direction:column;gap:14px;min-width:0">
          ${section("负责人负载", "未完成事项", `<div class="card-body tight">${ownerLoad(store.items)}</div>`)}
          ${section("条目构成", "按类型", `<div class="card-body tight">${kindBars(store.items)}</div>`)}
        </div>
      </div>

      <div class="grid-2 even">
        ${section("到期时间轴", "未完成且有截止日", `
          <div class="card-body tight">
            <div class="mini-list">
              ${openWithDue.slice(0, 6).map((item) => `
                <button class="mini-item" data-item="${item.id}" type="button">
                  ${kindPill(item.kind, KIND_LABEL[item.kind])}
                  <b>${esc(item.title)}</b>
                  <span>${dueTag(item, store.asOf) || `<span class="tag">${esc(fmtDate(item.due))}</span>`}</span>
                </button>`).join("") || `<div class="empty">还没有带截止日的事项</div>`}
            </div>
          </div>`)}

        ${section("风险", "未关闭", `
          <div class="card-body tight">
            <div class="mini-list">
              ${risks.slice(0, 6).map((item) => `
                <button class="mini-item" data-item="${item.id}" type="button">
                  <b>${esc(item.title)}</b>
                  <span>${statusPill(item.status, STATUS_LABEL[item.status])}</span>
                </button>`).join("") || `<div class="empty">没有未关闭的风险</div>`}
            </div>
          </div>`)}
      </div>

      ${section("最近动作", "只记录本次会话", `
        <div class="card-body tight">
          <ul class="feed">
            ${active.map((entry) => `<li><time>${fmtTime(entry.at)}</time><span>${esc(entry.text)}</span></li>`).join("")}
          </ul>
        </div>`)}
    `;
  },
};

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
      <div class="split">
        <div style="display:flex;flex-direction:column;gap:14px;min-width:0">
          <section class="card">
            <div class="card-head">
              <h2>来源纪要</h2>
              <div class="right"><button class="btn sm ghost" id="ingestClear">清空</button></div>
            </div>
            <div class="card-body" style="display:flex;flex-direction:column;gap:12px">
              <div class="source-tabs" id="ingestSources">
                ${meetings.map((row) => `
                  <button type="button" data-source="${row.id}" class="${row.id === source ? "active" : ""}">${esc(row.name.replace(".md", ""))}</button>`).join("")}
                <button type="button" data-source="custom" class="${source === "custom" ? "active" : ""}">自定义粘贴</button>
              </div>
              <div class="field">
                <textarea class="textarea" id="ingestText" spellcheck="false" placeholder="把会议纪要或聊天记录原文贴在这里">${esc(ingest.text)}</textarea>
                <small id="ingestMeta">${meeting ? `识别到会议日期 ${esc(meetingDateOf(ingest.text))}，共 ${ingest.text.length} 字` : `共 ${ingest.text.length} 字`}</small>
              </div>
              <div style="display:flex;gap:8px;align-items:center">
                <button class="btn primary" id="ingestRun" type="button">
                  <svg viewBox="0 0 24 24"><path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M4 17v3h16v-3"/></svg>
                  抽取条目
                </button>
                <span class="tag">${store.threshold.toFixed(2)} 判重阈值</span>
              </div>
            </div>
          </section>

          <div class="pipeline">
            <div><span>1</span><b>读纪要</b><small>识别日期与参与人</small></div>
            <div><span>2</span><b>抽条目</b><small>本地规则引擎</small></div>
            <div><span>3</span><b>判重</b><small>余弦距离 ≤ ${store.threshold.toFixed(2)}</small></div>
            <div><span>4</span><b>写台账</b><small>新增或合并历史条目</small></div>
          </div>
        </div>

        <section class="card" id="ingestResult">
          ${renderCandidates()}
        </section>
      </div>`;
  },

  mount(root) {
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
      <div class="result-head"><h2>已写入台账</h2></div>
      <div class="card-body">
        <div class="banner ok">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/></svg>
          <span>新增 <b>${added}</b> 条，合并 <b>${merged}</b> 条。台账现在共 ${store.items.length} 条。</span>
        </div>
        <div style="display:flex;gap:8px;margin-top:14px">
          <button class="btn primary" data-go="ledger" type="button">去台账看结果</button>
          <button class="btn" data-go="reconcile" type="button">重新对账</button>
        </div>
      </div>`;
  }

  if (!ingest.candidates.length) {
    return `
      <div class="result-head"><h2>抽取结果</h2><span class="sub">等待抽取</span></div>
      <div class="empty"><b>还没有候选条目</b>选一份纪要，点「抽取条目」，这里会列出每条与台账的比对结果。</div>`;
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
          ${candidate.owner ? esc(candidate.owner) : "<span style=\"color:var(--ink-4)\">无人</span>"}
          ${candidate.due ? ` · ${esc(fmtDate(candidate.due))}` : ""}
          <br>${statusPill(candidate.status, STATUS_LABEL[candidate.status])}
        </div>
        <div class="verdict">
          <button type="button" data-toggle="${index}" title="点击切换判定：合并 / 新增">
            ${candidate.merge ? `<span class="tag unassigned">合并</span>` : `<span class="tag ok">新增</span>`}
          </button>
          <small>${distance === null ? "台账为空" : `距离 ${distance.toFixed(3)}`}</small>
          <small>${candidate.merge && candidate.matchedTitle ? `↳ ${esc(candidate.matchedTitle)}` : ""}</small>
        </div>
      </div>`;
  }).join("");

  const dupCount = ingest.candidates.filter((candidate) => candidate.merge && candidate.picked).length;
  const picked = ingest.candidates.filter((candidate) => candidate.picked).length;
  return `
    <div class="result-head">
      <h2>抽取结果</h2>
      <span class="sub">${ingest.candidates.length} 条 · 已勾选 ${picked} · 合并 ${dupCount} · 新增 ${picked - dupCount}</span>
      <div class="right">
        <div class="cand-tools">
          <button class="chip" data-bulk="all" type="button">全选</button>
          <button class="chip" data-bulk="none" type="button">清空</button>
          <button class="chip" data-bulk="new" type="button">只选新增</button>
          <button class="chip" data-bulk="merge" type="button">只选合并</button>
        </div>
        <button class="btn primary sm" id="ingestWrite" type="button" ${picked ? "" : "disabled"}>写入台账</button>
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
};

export const ledger = {
  title: "台账",
  sub: () => `共 ${store.items.length} 条`,

  render() {
    return `
      <section class="card">
        <div class="card-head" style="flex-wrap:wrap;gap:10px">
          <div class="search" style="position:relative;flex:1 1 220px;max-width:320px">
            <svg viewBox="0 0 24 24" style="position:absolute;left:10px;top:50%;transform:translateY(-50%);width:15px;height:15px;stroke:var(--ink-4);fill:none;stroke-width:1.8"><circle cx="11" cy="11" r="6"/><path d="M16 16l4 4"/></svg>
            <input class="input" id="ledgerSearch" placeholder="搜标题、详情、负责人" value="${esc(ledgerView.q)}" style="padding-left:31px">
          </div>
          <div class="chips" id="ledgerKinds">
            ${[["all", "全部类型"], ...KINDS.map((kind) => [kind, KIND_LABEL[kind]])].map(([value, label]) => `
              <button class="chip ${ledgerView.kind === value ? "on" : ""}" data-kind="${value}" type="button">${esc(label)}</button>`).join("")}
          </div>
          <div class="spacer"></div>
          <button class="btn sm" id="ledgerNew" type="button">+ 新增条目</button>
          <button class="btn sm ghost" id="ledgerExport" type="button">导出 JSON</button>
        </div>
        <div class="card-head" style="border-top:0;flex-wrap:wrap;gap:10px">
          <div class="chips" id="ledgerStatus">
            ${[["all", "全部状态"], ...STATUSES.map((status) => [status, STATUS_LABEL[status]])].map(([value, label]) => `
              <button class="chip ${ledgerView.status === value ? "on" : ""}" data-status="${value}" type="button">${esc(label)}</button>`).join("")}
          </div>
          <div class="chips">
            <button class="chip warn ${ledgerView.overdueOnly ? "on" : ""}" id="ledgerOverdue" type="button">只看超期</button>
            <button class="chip warn ${ledgerView.unassignedOnly ? "on" : ""}" id="ledgerUnassigned" type="button">只看无人认领</button>
          </div>
          <div class="spacer"></div>
          <span class="sub" id="ledgerCount"></span>
        </div>
        <div class="table-wrap" id="ledgerTable"></div>
      </section>`;
  },

  mount(root) {
    const table = $("#ledgerTable", root);
    const count = $("#ledgerCount", root);

    const draw = () => {
      const rows = filterItems();
      count.textContent = `${rows.length} / ${store.items.length} 条`;
      table.innerHTML = `
        <table class="data">
          <thead><tr><th style="width:52px">类型</th><th>条目</th><th style="width:92px">负责人</th><th style="width:104px">截止</th><th style="width:96px">状态</th><th style="width:120px">标记</th></tr></thead>
          <tbody>
            ${rows.map((item) => {
              const late = store.isOpen(item) && item.due && item.due < store.asOf;
              const noOwner = store.isOpen(item) && !item.owner;
              return `
                <tr data-item="${item.id}">
                  <td>${kindPill(item.kind, KIND_LABEL[item.kind])}</td>
                  <td class="title"><b>${esc(item.title)}</b>${item.detail && item.detail !== item.title ? `<small>${esc(item.detail)}</small>` : ""}</td>
                  <td>${item.owner ? esc(item.owner) : `<span style="color:var(--ink-4)">无人</span>`}</td>
                  <td class="num">${item.due ? esc(fmtDate(item.due)) : "—"}</td>
                  <td>
                    <select class="select" data-status-for="${item.id}" style="padding:3px 6px;font-size:12px">
                      ${STATUSES.map((status) => `<option value="${status}" ${status === item.status ? "selected" : ""}>${STATUS_LABEL[status]}</option>`).join("")}
                    </select>
                  </td>
                  <td>
                    ${late ? `<span class="tag due">已超期</span>` : ""}
                    ${noOwner ? `<span class="tag unassigned">无人认领</span>` : ""}
                  </td>
                </tr>`;
            }).join("") || `<tr><td colspan="6"><div class="empty"><b>没有符合条件的条目</b>换个筛选条件，或者先去收件箱录一段纪要。</div></td></tr>`}
          </tbody>
        </table>`;
    };

    const filterItems = () => {
      const q = ledgerView.q.trim().toLowerCase();
      let rows = store.items.filter((item) => {
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
      return rows.sort(byUrgency);
    };

    $("#ledgerSearch", root).addEventListener("input", (event) => {
      ledgerView.q = event.target.value;
      draw();
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

    $("#ledgerNew", root).addEventListener("click", () => openItem(null));

    $("#ledgerExport", root).addEventListener("click", () => {
      download(`relay-ledger-${store.asOf}.json`, JSON.stringify({ project: store.state.project, asOf: store.asOf, items: store.items }, null, 2));
      toast("台账已导出");
    });

    table.addEventListener("change", (event) => {
      const select = event.target.closest("[data-status-for]");
      if (!select) return;
      store.setStatus(select.dataset.statusFor, select.value);
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

    return `
      <div class="stat-row">
        <div class="stat"><span>超期</span><b style="color:var(--red)">${stats.overdue}</b><small>基准日之后仍会影响交接</small></div>
        <div class="stat"><span>无人认领</span><b style="color:var(--amber)">${stats.unassigned}</b><small>未完成且没有负责人</small></div>
        <div class="stat"><span>受阻</span><b>${blocked.length}</b><small>卡在外部依赖</small></div>
        <div class="stat"><span>待确认</span><b>${questions.length}</b><small>接手人需要先问清楚</small></div>
      </div>

      <div class="grid-2 even">
        ${section(`已超期 ${overdue.length}`, `按原定日期排`, `
          <div class="card-body tight">
            <div class="mini-list">
              ${overdue.map((item) => {
                const late = daysBetween(item.due, store.asOf);
                return `
                  <button class="mini-item" data-item="${item.id}" type="button">
                    ${kindPill(item.kind, KIND_LABEL[item.kind])}
                    <b>${esc(item.title)}</b>
                    <span class="tag due">逾期 ${late} 天</span>
                  </button>`;
              }).join("") || `<div class="empty">没有超期条目</div>`}
            </div>
          </div>`)}
        ${section(`没人认领 ${unassigned.length}`, `未完成且无负责人`, `
          <div class="card-body tight">
            <div class="mini-list">
              ${unassigned.map((item) => `
                <button class="mini-item" data-item="${item.id}" type="button">
                  ${kindPill(item.kind, KIND_LABEL[item.kind])}
                  <b>${esc(item.title)}</b>
                  <span>${statusPill(item.status, STATUS_LABEL[item.status])}</span>
                </button>`).join("") || `<div class="empty">每条都有负责人</div>`}
            </div>
          </div>`)}
      </div>

      <div class="grid-2 even">
        ${section(`受阻 ${blocked.length}`, `卡在外部依赖`, `
          <div class="card-body tight">
            <div class="mini-list">
              ${blocked.map((item) => `
                <button class="mini-item" data-item="${item.id}" type="button">
                  ${kindPill(item.kind, KIND_LABEL[item.kind])}
                  <b>${esc(item.title)}</b>
                  <span>${esc(item.owner || "无人")}${item.due ? ` · ${esc(fmtDate(item.due))}` : ""}</span>
                </button>`).join("") || `<div class="empty">没有受阻条目</div>`}
            </div>
          </div>`)}
        ${section(`待确认 ${questions.length}`, `先问清楚再交接`, `
          <div class="card-body tight">
            <div class="mini-list">
              ${questions.map((item) => `
                <button class="mini-item" data-item="${item.id}" type="button">
                  ${kindPill(item.kind, KIND_LABEL[item.kind])}
                  <b>${esc(item.title)}</b>
                  <span>${esc(item.owner || "无人认领")}</span>
                </button>`).join("") || `<div class="empty">没有悬而未决的问题</div>`}
            </div>
          </div>`)}
      </div>

      <div class="grid-2 even">
        ${section("状态矩阵", "类型 × 状态，用来找堆积", `
          <div class="table-wrap">${matrixTable()}</div>`)}
        ${section("负责人负载", `${stats.open} 条未完成`, `
          <div class="card-body tight">${ownerLoad(store.items)}</div>`)}
      </div>

      ${section("对账单", "基准日快照，可直接作为交接附件", `
        <div class="card-body">
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn primary" id="reportOpen" type="button">生成对账报告</button>
            <button class="btn" id="reportCopy" type="button">复制 Markdown</button>
            <button class="btn ghost" id="reportDownload" type="button">下载 .md</button>
          </div>
          <div class="report-preview" id="reportPreview">
            <div class="empty" style="padding:22px 0">点「生成对账报告」在这里预览，内容与下载文件一致</div>
          </div>
        </div>`)}
    `;
  },

  mount(root) {
    const report = () => buildReport();
    const preview = $("#reportPreview", root);
    const show = () => {
      preview.innerHTML = `<pre>${esc(report())}</pre>`;
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
  const rows = KINDS.map((kind) => {
    const cells = STATUSES.map((status) => store.items.filter((item) => item.kind === kind && item.status === status).length);
    const sum = cells.reduce((a, b) => a + b, 0);
    return `<tr><td>${KIND_LABEL[kind]}</td>${cells.map((count) => `<td class="${count >= 3 ? "hot" : ""}">${count || "·"}</td>`).join("")}<td>${sum}</td></tr>`;
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

const retrievalState = { query: "数据库压力太大怎么办", keyword: "连接池" };

export const retrieval = {
  title: "检索",
  sub: () => "关键词 / 语义 / 混合三路对比",

  render() {
    const docs = store.items.map((item) => `${item.title}\n${item.detail || ""}`);
    const avg = docs.length ? Math.round(docs.reduce((sum, doc) => sum + tokenize(doc).length, 0) / docs.length) : 0;
    const presets = [
      { q: "数据库压力太大怎么办", k: "连接池" },
      { q: "token 不一致会怎样", k: "token" },
      { q: "灰度怎么放量", k: "灰度" },
      { q: "发布推迟到什么时候", k: "推迟" },
    ];
    return `
      <section class="card">
        <div class="card-head"><h2>查询</h2><span class="sub">对当前台账 ${store.items.length} 条检索</span></div>
        <div class="card-body">
          <div class="query-grid">
            <div class="field">
              <label for="qSemantic">想查的事</label>
              <input class="input" id="qSemantic" value="${esc(retrievalState.query)}" placeholder="用一句话描述你要找的事">
            </div>
            <div class="field">
              <label for="qKeyword">关键词（全文匹配）</label>
              <input class="input" id="qKeyword" value="${esc(retrievalState.keyword)}" placeholder="精确词">
            </div>
          </div>
          <div class="presets" id="retrievalPresets">
            ${presets.map((preset) => `<button type="button" data-q="${esc(preset.q)}" data-k="${esc(preset.k)}">${esc(preset.q)}</button>`).join("")}
          </div>
        </div>
      </section>

      <div class="index-strip">
        <div><span>台账文档</span><b>${store.items.length}</b></div>
        <div><span>词表</span><b>${store.vectorizer.idf.size}</b></div>
        <div><span>平均词元</span><b>${avg}</b></div>
        <div><span>合并阈值</span><b>${store.threshold.toFixed(2)}</b></div>
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
      cols.innerHTML = `
        <div class="cols-3">
          ${column("只关键词", "命中次数排序", result.keywordRanking.slice(0, 6), items, (id) => {
            const item = items.get(id);
            const hits = countKeyword(`${item.title}\n${item.detail || ""}`, retrievalState.keyword);
            return `${hits} 次命中`;
          })}
          ${column("只语义", "余弦相似度（越大越近）", result.semanticRanking.slice(0, 6), items, (id) => {
            return (result.semanticScore.get(id) || 0).toFixed(4);
          }, true)}
          ${column("混合 RRF", "两路排名融合 · k=60", result.hybrid.slice(0, 6).map((row) => row.id), items, (id) => {
            const row = result.hybrid.find((entry) => entry.id === id);
            return (row?.score || 0).toFixed(4);
          }, true)}
        </div>`;

      const top = result.hybrid.slice(0, 3);
      const tokens = [...new Set(tokenize(retrievalState.query))];
      explain.innerHTML = `
        <section class="card">
          <div class="card-head"><h2>排序解释</h2><span class="sub">混合结果前三名的分数构成</span></div>
          <div class="card-body">
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

function column(title, sub, ids, items, scoreOf, highlight = false) {
  return `
    <section class="card">
      <div class="card-head"><h2>${esc(title)}</h2><span class="sub">${esc(sub)}</span></div>
      <div class="card-body" style="padding-top:6px;padding-bottom:6px">
        ${ids.length ? `<div class="rank-list">${ids.map((id, index) => {
          const item = items.get(id);
          if (!item) return "";
          return `
            <div class="rank" data-item="${item.id}" style="cursor:pointer">
              <span class="no">${index + 1}</span>
              <span><b>${esc(item.title)}</b><small>${KIND_LABEL[item.kind]} · ${item.owner || "无人认领"}</small></span>
              <span class="score ${highlight ? "hi" : ""}">${scoreOf(id)}</span>
            </div>`;
        }).join("")}</div>` : `<div class="empty">没有命中</div>`}
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
      <div class="split wide-right">
        <div style="display:flex;flex-direction:column;gap:14px;min-width:0">
          <section class="card">
            <div class="card-head"><h2>交接信息</h2></div>
            <div class="card-body" style="display:flex;flex-direction:column;gap:12px">
              <div class="field">
                <label for="hoObjective">项目目标</label>
                <textarea class="textarea" id="hoObjective" style="min-height:64px">${esc(handoffState.objective)}</textarea>
              </div>
              <div class="meta-grid">
                <div class="field"><label for="hoFrom">交出的人</label><input class="input" id="hoFrom" value="${esc(handoffState.from)}"></div>
                <div class="field"><label for="hoTo">接手的人</label><input class="input" id="hoTo" value="${esc(handoffState.to)}"></div>
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card-head"><h2>接手人核对</h2><span class="sub">三项都确认才能生成</span></div>
            <div class="card-body tight">
              <div class="check-list" id="hoChecks">
                ${checkRow("live_state", "看过实时台账", "确认清单来自当前状态，不是会议印象")}
                ${checkRow("capability", "能力对得上", "接手人有时间与权限处理这些待办")}
                ${checkRow("authorization", "授权已确认", "可以改动灰度配置与线上接口")}
              </div>
            </div>
          </section>

          <button class="btn primary" id="hoRun" type="button" style="justify-content:center;padding:10px">
            生成交接（契约 → 交接 → 回执 → 结果）
          </button>
        </div>

        <div style="min-width:0;display:flex;flex-direction:column;gap:14px">
          ${card}
          ${section(`交接记录 ${store.state.handoffs.length}`, "本机保存", `
            <div class="card-body tight">
              ${store.state.handoffs.length ? `<div class="mini-list">${store.state.handoffs.map((record) => `
                <button class="mini-item" data-handoff="${record.id}" type="button">
                  <b>${esc(record.from)} → ${esc(record.to)}</b>
                  <span class="sub" style="margin-left:auto;font-size:11.5px;color:var(--ink-4)">${fmtStmt(record.at)}</span>
                </button>`).join("")}</div>` : `<div class="empty">还没有生成过交接</div>`}
            </div>`)}
        </div>
      </div>`;
  },

  mount(root) {
    $("#hoObjective", root).addEventListener("input", (event) => {
      handoffState.objective = event.target.value;
      $("#handoffCard", root).outerHTML = buildCard();
      document.querySelector("#viewSub").textContent = handoff.sub();
    });
    $("#hoFrom", root).addEventListener("input", (event) => {
      handoffState.from = event.target.value;
      refreshCard();
    });
    $("#hoTo", root).addEventListener("input", (event) => {
      handoffState.to = event.target.value;
      refreshCard();
    });

    const refreshCard = () => {
      $("#handoffCard", root).outerHTML = buildCard();
      $("#viewSub").textContent = handoff.sub();
    };

    $("#hoChecks", root).addEventListener("change", (event) => {
      const box = event.target.closest("[data-check]");
      if (!box) return;
      handoffState.checks[box.dataset.check] = box.checked;
      updateRunState(root);
    });

    $("#hoRun", root).addEventListener("click", () => {
      const record = createHandoff();
      handoffState.checks = { live_state: false, capability: false, authorization: false };
      store.addHandoff(record);
      toast("交接已生成，记录在右侧列表");
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

function checkRow(key, title, sub) {
  return `
    <label class="check">
      <input type="checkbox" data-check="${key}" ${handoffState.checks[key] ? "checked" : ""}>
      <span><b>${esc(title)}</b><small>${esc(sub)}</small></span>
    </label>`;
}

function updateRunState(root) {
  const button = $("#hoRun", root);
  if (!button) return;
  const ready = Object.values(handoffState.checks).every(Boolean);
  button.disabled = !ready;
}

function buildCard() {
  const sections = cardSections();
  return `
    <article class="handoff-card" id="handoffCard">
      <header>
        <h2>${esc(store.state.project)} · 交接卡</h2>
        <p>截至 ${esc(store.asOf)}｜${esc(handoffState.from || "—")} → ${esc(handoffState.to || "—")}</p>
      </header>
      <div class="handoff-sec">
        <h3>目标</h3>
        <p style="margin:0;font-size:13px;color:var(--ink-2)">${esc(handoffState.objective || "（填写项目目标）")}</p>
      </div>
      ${["overdue", "unassigned", "open", "done", "decisions", "risks", "questions"].map((key) => {
        const group = sections[key];
        if (!group.items.length) return "";
        return `
          <div class="handoff-sec">
            <h3>${esc(group.title)}<span>${group.items.length}</span></h3>
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

  const label = (item) => `<b>${esc(item.title)}</b>｜${esc(item.owner || "无人认领")}${item.due ? `｜原定 ${esc(fmtDate(item.due))}` : ""}`;
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
    lines.push(...group.items.map((item) => `- ${item.replace(/<[^>]+>/g, "")}`));
    lines.push("");
  }
  lines.push("## 交接步骤");
  lines.push(...record.steps.map((step) => `- ${step.name}｜position=${step.position}｜${step.detail}`));
  return lines.join("\n");
}

function showHandoff(record) {
  const body = `
    <div class="steps">
      ${record.steps.map((step, index) => `
        <div class="step done">
          <span class="idx">${index + 1}</span>
          <span><b>${esc(step.name)}</b><small>position=${step.position} · ${esc(step.detail)}</small></span>
          <em>${fmtTime(step.at)}</em>
        </div>`).join("")}
    </div>
    <div style="margin-top:14px">
      <pre>${esc(handoffMarkdown(record))}</pre>
    </div>`;
  openModal(
    `${record.from} → ${record.to}｜${fmtStmt(record.at)}`,
    body,
    `<button class="btn sm" data-copy type="button">复制</button>`,
    (modal) => {
      $("[data-copy]", modal).addEventListener("click", () => copyText(handoffMarkdown(record), "交接卡已复制"));
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
      <h2>${editing ? "编辑条目" : "新增条目"}</h2>
      <div class="right">
        ${editing ? `<button class="btn sm danger" data-delete type="button">删除</button>` : ""}
        <button class="icon-btn" data-close type="button" aria-label="关闭">
          <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>
        </button>
      </div>
    </div>
    <div class="drawer-body">
      <div class="field">
        <label>类型</label>
        <select class="select" data-field="kind">
          ${KINDS.map((kind) => `<option value="${kind}" ${draft.kind === kind ? "selected" : ""}>${KIND_LABEL[kind]}</option>`).join("")}
        </select>
      </div>
      <div class="field"><label>标题</label><input class="input" data-field="title" value="${esc(draft.title)}" placeholder="一句话说清这件事"></div>
      <div class="field"><label>详情</label><textarea class="textarea" data-field="detail" style="min-height:110px">${esc(draft.detail || "")}</textarea></div>
      <div class="meta-grid">
        <div class="field"><label>负责人</label><input class="input" data-field="owner" value="${esc(draft.owner || "")}" placeholder="留空 = 无人认领"></div>
        <div class="field"><label>截止</label><input class="input" type="date" data-field="due" value="${esc(draft.due || "")}"></div>
      </div>
      <div class="field">
        <label>状态</label>
        <select class="select" data-field="status">
          ${STATUSES.map((status) => `<option value="${status}" ${draft.status === status ? "selected" : ""}>${STATUS_LABEL[status]}</option>`).join("")}
        </select>
      </div>
      ${editing ? `<div class="field"><label>来源</label><pre>${esc(draft.source || "—")}\nid: ${esc(draft.id)}</pre></div>` : ""}
    </div>
    <div class="drawer-foot">
      <button class="btn primary" data-save type="button">${editing ? "保存修改" : "创建条目"}</button>
    </div>`;

  openDrawer(html, (drawer) => {
    const read = () => {
      const patch = {};
      $$("[data-field]", drawer).forEach((field) => { patch[field.dataset.field] = field.value.trim(); });
      return patch;
    };
    $("[data-close]", drawer).addEventListener("click", closeDrawer);
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
      del.addEventListener("click", () => {
        if (!confirm(`确定删除「${item.title}」？`)) return;
        store.removeItem(item.id);
        closeDrawer();
        toast("已删除");
      });
    }
  });
}
