/** 首次上手：产品说明弹窗 + 聚光灯分步引导。只在需要时出现，随时可重开。 */

import { store } from "./store.js";
import { $, esc, openModal, closeModal } from "./ui.js";
import { icon } from "./icons.js";

const FLAG = "relay.onboard.v1";

const CARDS = [
  { ic: "inbox", color: "#d9542b", bg: "#fdeee6", title: "收件箱：纪要进台账", text: "贴一段会议纪要，自动拆成决定 / 行动项 / 风险 / 待确认，并逐条判断是不是台账里已有的那件事。" },
  { ic: "ledger", color: "#2563eb", bg: "#e9efff", title: "台账：唯一事实", text: "同一件事只留一条，谁负责、到哪天、什么状态，随时改、随时搜、随时导出。" },
  { ic: "reconcile", color: "#b45309", bg: "#fdf1de", title: "对账：找出说不清的部分", text: "按基准日算出超期、无人认领、受阻与待确认，一键生成可发出去的对账单。" },
  { ic: "handoff", color: "#0d7d8a", bg: "#e4f3f4", title: "交接：带着状态走", text: "接手人三项核对通过后生成交接卡，契约 → 交接 → 回执 → 结果四步留痕。" },
];

export function openWelcome() {
  const body = `
    <div class="welcome">
      <div class="welcome-hero">
        <span class="hero-eyebrow">${icon("baton")} 接力棒 Relay · 工作台</span>
        <h3>把开过的会，变成一张能交接的台账</h3>
        <p>同一件事在三次会议里被说了三遍，没人说得清现在是什么状态；人一调走，决定和约束就留在聊天记录里。
        Relay 把纪要抽成条目、和已有台账判重合并，再按基准日对账，最后生成带状态的交接卡。</p>
      </div>
      <div class="welcome-body">
        <div class="welcome-grid">
          ${CARDS.map((card) => `
            <div class="welcome-card">
              <span class="wc-ic" style="background:${card.bg};color:${card.color}">${icon(card.ic)}</span>
              <span><b>${esc(card.title)}</b><small>${esc(card.text)}</small></span>
            </div>`).join("")}
        </div>
        <div class="welcome-foot">
          <span class="sub">当前载入示例项目「${esc(store.state.project)} 登录改造」${store.items.length} 条台账，改动只存在本机浏览器。</span>
          <div class="right">
            <button class="btn" type="button" data-welcome-close>直接开始</button>
            <button class="btn primary" type="button" data-welcome-tour>${icon("play")} 跟着走一遍（8 步）</button>
          </div>
        </div>
      </div>
    </div>`;

  openModal("这个系统是什么，怎么用", body, "", (modal) => {
    $("[data-welcome-close]", modal).addEventListener("click", () => { markSeen(); closeModal(); });
    $("[data-welcome-tour]", modal).addEventListener("click", () => { markSeen(); closeModal(); startTour(); });
    $("[data-close-modal]", modal).addEventListener("click", markSeen);
  });
}

export function maybeWelcome() {
  try {
    if (localStorage.getItem(FLAG)) return false;
  } catch { /* 隐私模式：每次都提示 */ }
  openWelcome();
  return true;
}

function markSeen() {
  try { localStorage.setItem(FLAG, "1"); } catch { /* ignore */ }
}

/* ------------------------------------------------------------------ */
/* 聚光灯引导                                                          */
/* ------------------------------------------------------------------ */

const STEPS = [
  {
    view: "overview", target: ".hero", ic: "compass", title: "先看这条链路",
    text: "工作台按「读纪要 → 判重合并 → 对账 → 交接」四步组织。卡片会随你的操作变成已完成，点任意一步可以直接跳过去。",
  },
  {
    view: "ingest", target: "#ingestRun", ic: "inbox", title: "第一步：抽取条目",
    text: "左边已经放好一份真实周会纪要。点「抽取条目」，右边会列出抽到的每一条，以及它和台账的比对结果。也可以换成自定义粘贴。",
  },
  {
    view: "ingest", target: "#ingestResult", ic: "merge", title: "第二步：看判重再写入",
    text: "每条都有一把距离标尺：指针在阈值左边判「合并」，右边判「新增」，点标签可以人工改判。勾选后点「写入台账」。",
  },
  {
    view: "ledger", target: "#ledgerTable", ic: "ledger", title: "第三步：台账就是唯一事实",
    text: "搜索、按类型/状态筛选、排序都在这里。点一行打开详情抽屉可改可删；勾选多行能批量改状态或删除，删错了可以撤销。",
  },
  {
    view: "reconcile", target: "#reportOpen", ic: "reconcile", title: "第四步：对账",
    text: "超期、无人认领、受阻、待确认四张清单，加上类型 × 状态热力矩阵。点「生成对账报告」得到可直接发出去的 Markdown。",
  },
  {
    view: "retrieval", target: "#retrievalCols", ic: "search", title: "验证：为什么能认出同一件事",
    text: "同一个问题分别走关键词、语义、混合三路检索，并排看命中差异；下方「排序解释」列出前三名的分数构成。",
  },
  {
    view: "handoff", target: "#hoChecks", ic: "shield", title: "第五步：接手人先核对",
    text: "看过实时台账、能力对得上、授权已确认——三项都勾上，生成按钮才会解锁。这是交接契约的硬要求。",
  },
  {
    view: "handoff", target: "#hoRun", ic: "handoff", title: "生成交接卡",
    text: "点它生成「工作契约 → Prepared Handoff → 确认回执 → 任务结果」四步记录，右侧交接卡可复制、可下载，记录保存在本机。",
  },
];

let tour = null;

export function startTour(index = 0) {
  stopTour();
  const layer = document.createElement("div");
  layer.className = "tour-layer";
  layer.innerHTML = `
    <div class="tour-hole" hidden></div>
    <div class="tour-tip" role="dialog" aria-label="使用引导">
      <div class="tt-step"></div>
      <h3></h3>
      <p></p>
      <div class="tt-foot">
        <div class="tour-dots">${STEPS.map(() => "<i></i>").join("")}</div>
        <button class="btn sm ghost" type="button" data-tour-skip>跳过</button>
        <button class="btn sm" type="button" data-tour-prev>${icon("chevronLeft")} 上一步</button>
        <button class="btn sm primary" type="button" data-tour-next>下一步 ${icon("chevronRight")}</button>
      </div>
    </div>`;
  document.body.appendChild(layer);
  tour = { layer, index: Math.max(0, Math.min(index, STEPS.length - 1)) };

  layer.addEventListener("click", (event) => {
    if (event.target.closest("[data-tour-skip]")) { stopTour(); return; }
    if (event.target.closest("[data-tour-prev]")) { go(tour.index - 1); return; }
    if (event.target.closest("[data-tour-next]")) {
      if (tour.index >= STEPS.length - 1) { stopTour(); return; }
      go(tour.index + 1);
    }
  });

  tour.onKey = (event) => {
    if (!tour) return;
    if (event.key === "Escape") stopTour();
    if (event.key === "ArrowRight") go(tour.index + 1);
    if (event.key === "ArrowLeft") go(tour.index - 1);
  };
  tour.onMove = () => position();
  document.addEventListener("keydown", tour.onKey);
  window.addEventListener("resize", tour.onMove);
  window.addEventListener("scroll", tour.onMove, true);

  go(tour.index);
}

export function stopTour() {
  if (!tour) return;
  document.removeEventListener("keydown", tour.onKey);
  window.removeEventListener("resize", tour.onMove);
  window.removeEventListener("scroll", tour.onMove, true);
  tour.layer.remove();
  tour = null;
}

function go(index) {
  if (!tour) return;
  if (index < 0) index = 0;
  if (index >= STEPS.length) { stopTour(); return; }
  tour.index = index;
  const step = STEPS[index];
  document.dispatchEvent(new CustomEvent("relay:navigate", { detail: step.view }));

  const tip = $(".tour-tip", tour.layer);
  $(".tt-step", tip).textContent = `第 ${index + 1} / ${STEPS.length} 步`;
  $("h3", tip).innerHTML = `${icon(step.ic)} ${esc(step.title)}`;
  $("p", tip).textContent = step.text;
  $$(".tour-dots i", tip).forEach((dot, i) => dot.classList.toggle("on", i === index));
  $("[data-tour-prev]", tip).disabled = index === 0;
  $("[data-tour-next]", tip).innerHTML = index === STEPS.length - 1
    ? `完成 ${icon("check")}`
    : `下一步 ${icon("chevronRight")}`;

  const target = document.querySelector(step.target);
  if (target) target.scrollIntoView({ block: "center", behavior: "smooth" });
  setTimeout(position, 260);
  position();
}

function position() {
  if (!tour) return;
  const step = STEPS[tour.index];
  const target = document.querySelector(step.target);
  const hole = $(".tour-hole", tour.layer);
  const tip = $(".tour-tip", tour.layer);
  if (!target) { hole.hidden = true; return; }

  const rect = target.getBoundingClientRect();
  const pad = 6;
  hole.hidden = false;
  hole.style.left = `${rect.left - pad}px`;
  hole.style.top = `${rect.top - pad}px`;
  hole.style.width = `${rect.width + pad * 2}px`;
  hole.style.height = `${rect.height + pad * 2}px`;

  const tipRect = tip.getBoundingClientRect();
  const margin = 14;
  let top = rect.bottom + margin;
  if (top + tipRect.height > window.innerHeight - 12) top = rect.top - tipRect.height - margin;
  if (top < 12) top = Math.max(12, Math.min(window.innerHeight - tipRect.height - 12, rect.top + 12));
  let left = rect.left + rect.width / 2 - tipRect.width / 2;
  left = Math.max(12, Math.min(left, window.innerWidth - tipRect.width - 12));
  tip.style.top = `${top}px`;
  tip.style.left = `${left}px`;
}

function $$(selector, root) { return [...root.querySelectorAll(selector)]; }

/* ------------------------------------------------------------------ */
/* 上手进度                                                            */
/* ------------------------------------------------------------------ */

export const MILESTONES = [
  { key: "extract", view: "ingest", ic: "inbox", title: "抽一次纪要", hint: "收件箱 → 抽取条目" },
  { key: "write", view: "ingest", ic: "merge", title: "写入台账", hint: "勾选候选 → 写入台账" },
  { key: "reconcile", view: "reconcile", ic: "reconcile", title: "生成对账单", hint: "对账 → 生成对账报告" },
  { key: "handoff", view: "handoff", ic: "handoff", title: "完成一次交接", hint: "交接 → 三项核对 → 生成" },
];

export function progress() {
  const done = MILESTONES.filter((row) => store.state.milestones?.[row.key]).length;
  return { done, total: MILESTONES.length, next: MILESTONES.find((row) => !store.state.milestones?.[row.key]) || null };
}