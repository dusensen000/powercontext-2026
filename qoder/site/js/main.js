/** 应用入口：路由、顶栏、状态订阅、全局交互。 */

import { store } from "./store.js";
import { $, $$, esc, toast, closeDrawer, closeModal, openModal, download } from "./ui.js";
import {
  overview, inbox, ledger, reconcile, retrieval, handoff, openItem,
} from "./views.js";
import { KIND_LABEL } from "./engine.js";

const VIEWS = { overview, ingest: inbox, ledger, reconcile, retrieval, handoff };
const ORDER = ["overview", "ingest", "ledger", "reconcile", "retrieval", "handoff"];
let current = "overview";

function navigate(key) {
  if (!VIEWS[key]) key = "overview";
  current = key;
  $$("#nav button").forEach((button) => button.classList.toggle("active", button.dataset.view === key));
  render();
  window.scrollTo({ top: 0 });
}

function render() {
  const view = VIEWS[current];
  const root = $("#view");
  $("#viewTitle").textContent = view.title;
  $("#viewSub").textContent = typeof view.sub === "function" ? view.sub() : view.sub || "";

  root.innerHTML = view.render();
  view.mount?.(root);

  const stats = store.stats();
  $("#countLedger").textContent = String(stats.total);
  $("#countHandoff").textContent = String(store.state.handoffs.length);
  $("#projectMeta").textContent = `${stats.total} 条 · ${stats.open} 未完成`;

  const overdueBadge = $("#badgeOverdue");
  overdueBadge.hidden = stats.overdue === 0;
  overdueBadge.textContent = String(stats.overdue);

  $("#asOf").value = store.asOf;
  document.title = `接力棒 Relay · ${view.title}`;
}

function bootShell() {
  $("#nav").addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (button) navigate(button.dataset.view);
  });

  document.addEventListener("relay:navigate", (event) => navigate(event.detail));
  document.addEventListener("relay:rerender", render);

  $("#asOf").addEventListener("change", (event) => {
    if (!event.target.value) return;
    store.setAsOf(event.target.value);
    toast(`对账基准日改为 ${event.target.value}`);
  });

  // 条目详情：全局委托，表格、列表、检索结果共用
  document.addEventListener("click", (event) => {
    if (event.target.closest("select, input")) return;
    const row = event.target.closest("[data-item]");
    if (row) { openItem(row.dataset.item); return; }
    const go = event.target.closest("[data-go]");
    if (go) navigate(go.dataset.go);
  });

  $("#modal").addEventListener("click", (event) => {
    if (event.target.id === "modal") closeModal();
    if (event.target.closest("[data-close-modal]")) closeModal();
  });

  $("#drawer").addEventListener("click", (event) => {
    if (event.target === $("#drawer")) closeDrawer();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { closeModal(); closeDrawer(); }
  });

  $("#btnSettings").addEventListener("click", openSettings);
  $("#btnReset").addEventListener("click", () => {
    if (!confirm("清空本机改动，回到初始 14 条台账？")) return;
    store.reset();
    toast("已重置为初始数据");
  });
}

function openSettings() {
  const body = `
    <div class="field" style="margin-bottom:18px">
      <label for="threshold">判重阈值（余弦距离）</label>
      <div style="display:flex;align-items:center;gap:12px">
        <input type="range" id="threshold" min="0.30" max="0.90" step="0.01" value="${store.threshold}" style="flex:1;accent-color:var(--relay)">
        <b id="thresholdValue" style="font-variant-numeric:tabular-nums;font-size:15px">${store.threshold.toFixed(2)}</b>
      </div>
      <small>候选条目与台账里最相似条目的距离不超过它，就判为同一件事的更新；超过就是新条目。改完对下一次抽取生效。</small>
    </div>
    <div class="field" style="margin-bottom:18px">
      <label>存储</label>
      <small>台账、交接记录与设置都存在本机浏览器里，不会上传。换浏览器或清缓存会回到初始数据。</small>
    </div>
    <div class="field">
      <label>导出</label>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn sm" id="exportAll" type="button">导出全部状态 JSON</button>
        <button class="btn sm ghost" id="resetFromSettings" type="button">重置为初始数据</button>
      </div>
    </div>`;

  openModal("设置", body, "", (modal) => {
    const range = $("#threshold", modal);
    range.addEventListener("input", () => {
      $("#thresholdValue", modal).textContent = Number(range.value).toFixed(2);
      store.setThreshold(Number(range.value));
    });
    $("#exportAll", modal).addEventListener("click", () => {
      download("relay-state.json", JSON.stringify(store.state, null, 2));
      toast("已导出");
    });
    $("#resetFromSettings", modal).addEventListener("click", () => {
      if (!confirm("确认重置？本机改动会丢失。")) return;
      store.reset();
      closeModal();
      toast("已重置为初始数据");
    });
  });
}

store.subscribe(() => {
  render();
});

(async function start() {
  try {
    await store.init();
  } catch (error) {
    $("#view").innerHTML = `
      <div class="banner">
        <span>初始数据没能加载（${esc(error.message)}）。如果你是在本地直接双击打开的页面，请用 HTTP 方式访问，例如
        <code>python3 -m http.server</code>，或者直接看线上版本。</span>
      </div>`;
    console.error(error);
    return;
  }

  bootShell();
  const hash = location.hash.replace("#", "");
  navigate(ORDER.includes(hash) ? hash : "overview");
  store.emit();
})();
