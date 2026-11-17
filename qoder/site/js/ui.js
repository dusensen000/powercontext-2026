/** 通用小工具：转义、格式化、抽屉、弹窗、提示。 */

export const esc = (value) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export function daysBetween(from, to) {
  const a = Date.parse(`${from}T00:00:00`);
  const b = Date.parse(`${to}T00:00:00`);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.round((b - a) / 86400000);
}

export const fmtDate = (value) => (value ? value.replace(/-/g, ".") : "—");
export const fmtTime = (iso) => {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
};
export const fmtStmt = (iso) => {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

export function toast(text) {
  const wrap = $("#toast");
  wrap.innerHTML = `<div class="toast">${esc(text)}</div>`;
  wrap.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { wrap.hidden = true; }, 2600);
}

export function closeDrawer() {
  const drawer = $("#drawer");
  drawer.hidden = true;
  drawer.innerHTML = "";
  document.body.style.overflow = "";
}

export function openDrawer(html, onMount) {
  const drawer = $("#drawer");
  drawer.innerHTML = html;
  drawer.hidden = false;
  document.body.style.overflow = "hidden";
  onMount?.(drawer);
}

export function closeModal() {
  const modal = $("#modal");
  modal.hidden = true;
  modal.innerHTML = "";
}

export function openModal(title, bodyHtml, actionsHtml = "", onMount) {
  const modal = $("#modal");
  modal.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>${esc(title)}</h2>
        <div class="right">
          ${actionsHtml}
          <button class="icon-btn" type="button" data-close-modal aria-label="关闭">
            <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>
          </button>
        </div>
      </div>
      <div class="modal-body">${bodyHtml}</div>
    </div>`;
  modal.hidden = false;
  onMount?.(modal);
  return modal;
}

export function copyText(text, message = "已复制") {
  const done = () => toast(message);
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallback());
  } else {
    fallback();
  }
  function fallback() {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); done(); } catch { toast("复制失败，请手动选择"); }
    area.remove();
  }
}

export function download(filename, text) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const kindPill = (kind, label) => `<span class="pill ${kind}">${esc(label)}</span>`;

export const statusPill = (status, label) =>
  `<span class="status-pill ${status}">${esc(label)}</span>`;
