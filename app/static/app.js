"use strict";
/* Forit Lab — клиентская логика. Vanilla JS, без сборки и зависимостей. */

// ---------- утилиты ----------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// Tab в пустом поле с placeholder — подставляет пример (и оставляет фокус на поле)
document.addEventListener("keydown", (e) => {
  if (e.key !== "Tab" || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;
  const t = e.target;
  if (!t || (t.tagName !== "INPUT" && t.tagName !== "TEXTAREA")) return;
  if (t.type === "file" || t.type === "checkbox") return;
  if (t.placeholder && t.value === "") {
    e.preventDefault();
    t.value = t.placeholder;
    t.dispatchEvent(new Event("input", { bubbles: true }));
  }
});
const el = (tag, props = {}, ...kids) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// URL для показа: раскодируем percent-encoding (кириллица читаемо), кривой ввод оставляем как есть.
function prettyUrl(u) { try { return decodeURI(String(u || "")); } catch { return String(u || ""); } }
const fmtNum = (n) => (typeof n === "number" ? n.toLocaleString("ru-RU") : n);

// ---------- сеть ----------
class ApiError extends Error {
  constructor(message, detail, code) { super(message); this.detail = detail; this.code = code; }
}
async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new ApiError("Сеть недоступна. Проверьте соединение.", String(e));
  }
  const ctype = res.headers.get("content-type") || "";
  if (!res.ok) {
    // Ошибки backend всегда имеют форму {error:{code,message,detail}} — не вываливаем traceback.
    if (ctype.includes("json")) {
      const body = await res.json().catch(() => null);
      const err = body && body.error;
      if (err) throw new ApiError(err.message || "Ошибка запроса", err.detail, err.code);
    }
    throw new ApiError(`Ошибка ${res.status}`, null, String(res.status));
  }
  if (ctype.includes("json")) return res.json();
  return res.text();
}

function toast(message, kind = "") {
  const t = el("div", { class: `toast ${kind}` }, message);
  $("#toasts").append(t);
  setTimeout(() => { t.style.opacity = "0"; setTimeout(() => t.remove(), 250); }, 3500);
}

// состояния для контейнера результатов
const State = {
  loading: (msg = "Загружаем…") => el("div", { class: "state" }, el("div", { class: "spinner" }), msg),
  empty: (msg = "Ничего не найдено") => el("div", { class: "state" }, el("div", { class: "ico" }, "🕳️"), msg),
  error: (err) => el("div", { class: "state error" },
    el("div", { class: "ico" }, "⚠️"),
    el("div", {}, err.message || "Что-то пошло не так"),
    err.detail ? el("div", { class: "detail" }, typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail)) : null),
};
function render(container, node) { container.replaceChildren(node); }
async function withState(container, loadingMsg, fn) {
  render(container, State.loading(loadingMsg));
  try {
    const node = await fn();
    render(container, node || State.empty());
  } catch (e) {
    render(container, State.error(e instanceof ApiError ? e : new ApiError(String(e))));
  }
}

const sevBadge = (sev, text) => el("span", { class: `badge ${sev}` }, text || sev);
const MARK = { ok: "✓", info: "·", warn: "⚠", alert: "✕" };

// ---------- роутинг ----------
const VIEWS = ["home", "about", "parser", "chaos", "file", "unicode2", "rename", "print", "harvester", "finder", "burner", "drift", "unicode"];
let currentView = null, prevView = null;
function navigate(view) {
  if (!VIEWS.includes(view)) view = "home";
  if (view === "harvester") view = "parser"; // миграция: Web Harvester → Web Parser
  // navigate срабатывает дважды (клик + hashchange) — запоминаем предыдущую вью только при реальной смене
  if (view !== currentView) { prevView = currentView; currentView = view; }
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  $$("#nav button[data-nav]").forEach((b) => b.classList.toggle("active", b.dataset.nav === view));
  setMenu(false);
  closeHint();
  closeAboutDialog({ restoreFocus: false });
  if (location.hash !== `#${view}`) location.hash = view;
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (view === "home") initHome();
  if (view === "about") initAbout();
  if (view === "finder") initFinderOnce();
  if (view === "burner") initBurnerOnce();
  if (view === "unicode") initUnicodeOnce();
  if (view === "chaos") { buildChaosUrl(); initChaosOnce(); showChaosHandoff(); }
  if (view === "parser") initParserOnce();
  if (view === "file") initFileInspectorOnce();
  if (view === "unicode2") initUnicode2Once();
  if (view === "rename") initBatchRenameOnce();
  if (view === "print") initPrintOnce();
}
window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));
document.addEventListener("click", (e) => {
  // «← Назад»: туда, откуда пришли; если страницу открыли прямой ссылкой — на главную
  if (e.target.closest("[data-back]")) { e.preventDefault(); navigate(prevView && prevView !== currentView ? prevView : "home"); return; }
  const nav = e.target.closest("[data-nav]");
  if (nav) { e.preventDefault(); navigate(nav.dataset.nav); }
});

// ---------- мобильное меню ----------
// На узких экранах (см. breakpoint в styles.css) #nav превращается в выпадающую панель под хедером.
function setMenu(open) {
  const btn = $("#navToggle");
  if (!btn) return;
  document.documentElement.classList.toggle("nav-open", open);
  btn.setAttribute("aria-expanded", String(open));
  btn.setAttribute("aria-label", open ? "Закрыть меню" : "Открыть меню");
}
$("#navToggle").addEventListener("click", () => setMenu(!document.documentElement.classList.contains("nav-open")));
$("#navScrim").addEventListener("click", () => setMenu(false));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && document.documentElement.classList.contains("nav-open")) { setMenu(false); $("#navToggle").focus(); }
});
// повернули планшет / расширили окно до десктопа — меню не должно остаться «открытым» с заблокированным скроллом
matchMedia("(min-width: 1100px)").addEventListener("change", (e) => { if (e.matches) setMenu(false); });

// ---------- «Как это работает»: справка (большой «?») ----------
// Нативный <dialog>: showModal даёт top layer, ловушку фокуса и закрытие по Escape (iOS Safari 15.4+).
let dialogReturnFocus = null;
function openAboutDialog(trigger) {
  const dlg = $("#aboutDialog");
  if (!dlg || dlg.open) return;
  closeHint();
  dialogReturnFocus = trigger || document.activeElement;
  if (typeof dlg.showModal === "function") dlg.showModal();
  else dlg.setAttribute("open", "");
  document.documentElement.classList.add("modal-open");
}
function closeAboutDialog({ restoreFocus = true } = {}) {
  const dlg = $("#aboutDialog");
  if (!dlg || !dlg.open) return;
  if (!restoreFocus) dialogReturnFocus = null; // уходим на другую вью — фокусировать скрытую кнопку незачем
  if (typeof dlg.close === "function") dlg.close();
  else { dlg.removeAttribute("open"); onAboutDialogClosed(); }
}
function onAboutDialogClosed() {
  document.documentElement.classList.remove("modal-open");
  if (dialogReturnFocus && document.contains(dialogReturnFocus)) dialogReturnFocus.focus({ preventScroll: true });
  dialogReturnFocus = null;
}
$("#aboutInfoBtn").addEventListener("click", (e) => openAboutDialog(e.currentTarget));
$("#aboutDialog").addEventListener("close", onAboutDialogClosed);
// тап по затемнению (вне карточки) попадает в сам <dialog>; кнопки «✕»/«Понятно» помечены data-close
$("#aboutDialog").addEventListener("click", (e) => {
  if (e.target === e.currentTarget || e.target.closest("[data-close]")) closeAboutDialog();
});
// Tab/Shift+Tab ходят по кругу внутри справки, а не уходят в адресную строку браузера
$("#aboutDialog").addEventListener("keydown", (e) => {
  if (e.key !== "Tab") return;
  const items = $$("button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])", e.currentTarget)
    .filter((n) => !n.disabled && n.getClientRects().length);
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
});

// ---------- «Как это работает»: подсказка о странице (маленький «?») ----------
// Видна, пока её закрепили тапом/кликом, навели мышью или сфокусировали с клавиатуры.
const hintState = { pinned: false, hover: false, focus: false };
function syncHint() {
  const open = hintState.pinned || hintState.hover || hintState.focus;
  $("#aboutHintBtn").setAttribute("aria-expanded", String(open));
  $("#aboutHint").classList.toggle("open", open);
}
function closeHint() {
  hintState.pinned = hintState.hover = hintState.focus = false;
  if ($("#aboutHintBtn")) syncHint();
}
$("#aboutHintBtn").addEventListener("click", () => {
  if (hintState.pinned) closeHint();
  else { hintState.pinned = true; syncHint(); }
});
$("#aboutHintWrap").addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") { hintState.hover = true; syncHint(); } });
$("#aboutHintWrap").addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") { hintState.hover = false; syncHint(); } });
$("#aboutHintBtn").addEventListener("focus", (e) => { if (e.target.matches(":focus-visible")) { hintState.focus = true; syncHint(); } });
$("#aboutHintBtn").addEventListener("blur", () => { hintState.focus = false; syncHint(); });
document.addEventListener("pointerdown", (e) => {
  if (hintState.pinned && !e.target.closest("#aboutHintWrap")) closeHint();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && $("#aboutHint").classList.contains("open")) closeHint();
});

// ---------- тема ----------
// Ember — тёмный дизайн, тема фиксирована на dark (переключателя нет).
document.documentElement.dataset.theme = "dark";

// =====================================================================
// ГЛАВНАЯ
// =====================================================================
// Иконки для инструментов без готовой картинки (line-art в стиль tool-hero).
const TICON = {
  file: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><circle cx="12" cy="14" r="3"/><path d="m16.5 18.5-1.6-1.6"/></svg>`,
  rename: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="m14.5 11-3.5 3.5m0 0L8 11m3 3.5V8"/></svg>`,
  print: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9V3h12v6"/><path d="M6 18H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2"/><path d="M6 14h12v7H6z"/></svg>`,
};
const TOOLS_META = {
  parser: { title: "Web Parser", sub: "Собери данные с сайта в таблицу", img: "harvester", accent: "#22d3ee", tags: ["HTML", "Table", "Dataset"] },
  chaos: { title: "Chaos", sub: "Пассивный аудит безопасности сайта", img: "chaos", accent: "#f43f5e", tags: ["Headers", "TLS", "Cookies"] },
  file: { title: "File Inspector", sub: "Что файл знает о тебе — и как это вычистить", icon: TICON.file, accent: "#c084fc", tags: ["Metadata", "GPS", "SHA-256"] },
  unicode2: { title: "Unicode", sub: "Найди невидимые проблемы в тексте", img: "unicode", accent: "#a855f7", tags: ["Text", "Unicode", "Clean"] },
  rename: { title: "Batch Rename", sub: "Переименуй пачку файлов по правилам", icon: TICON.rename, accent: "#3b82f6", tags: ["Rules", "Preview", "ZIP"] },
  print: { title: "Print", sub: "Подготовь текст к печати через браузер", icon: TICON.print, accent: "#22c55e", tags: ["A4", "Поля", "Печать"] },
};
// ---------- О проекте / Как это работает ----------
const ABOUT = [
  { id: "parser", name: "Web Parser", accent: "#22d3ee",
    what: "Принимает ссылку на публичную страницу и вытаскивает всё структурированное: таблицы, повторяющиеся карточки-сущности, ссылки, картинки, формы, метаданные и JSON-LD. Умеет обходить каталог по страницам в один датасет и повторить извлечение кодом (curl + Python).",
    why: "Быстро превратить любую веб-страницу в датасет, не открывая DevTools и не пиша парсер под каждый сайт.",
    example: "Дал ссылку на статью со списком стран → получил CSV с таблицей ВВП одним кликом." },
  { id: "chaos", name: "Chaos", accent: "#f43f5e",
    what: "Пассивный аудит безопасности сайта: заголовки (HSTS, CSP, X-Frame-Options), TLS, cookies, CORS, редиректы, утечки версий и раскрытие данных. Проверяет одну страницу или обходит весь сайт. Находки с уровнем и доказательством, без разрушительных запросов.",
    why: "Увидеть слабые места конфигурации до того, как их найдёт кто-то другой — без эксплойтов и брутфорса.",
    example: "Проверил свой лендинг → увидел отсутствие HSTS и слишком широкий CORS с доказательствами." },
  { id: "file", name: "File Inspector", accent: "#c084fc",
    what: "Показывает, что файл знает о тебе: имя, тип, размер, SHA-256 и метаданные — GPS-координаты, модель устройства, ПО, автор, даты. Чувствительное можно вычистить и скачать очищенную копию (оригинал не меняется).",
    why: "Не выложить в сеть фото с домашними координатами или документ с именем автора и историей правок.",
    example: "Перетащил фото с телефона → увидел GPS съёмки, вычистил и скачал чистую копию." },
  { id: "unicode2", name: "Unicode", accent: "#a855f7",
    what: "Вскрывает невидимый текстовый мусор: zero-width символы, NBSP, bidi, управляющие знаки, разницу NFC/NFD, smart-quotes и кириллицу под видом латиницы. Clean Copy безопасно чистит строку, есть нормализация и escape — с предпросмотром изменений.",
    why: "Найти причину, почему «одинаковые» строки не равны, JOIN не сходится, а поиск не находит очевидное.",
    example: "Вставил логин из формы → нашёл zero-width в конце, из-за которого не проходила авторизация." },
  { id: "rename", name: "Batch Rename", accent: "#3b82f6",
    what: "Массовое переименование по правилам (префикс/суффикс/замена/regex/регистр/нумерация). Сначала превью old→new и проверка конфликтов, применение — только после предпросмотра. На выходе ZIP с новыми именами; оригиналы на компьютере не трогаются.",
    why: "Привести пачку файлов к единому порядку без ручного переименования и без риска затереть оригиналы.",
    example: "Добавил префикс с датой и сквозную нумерацию к 40 фото → скачал готовый ZIP." },
  { id: "print", name: "Print", accent: "#22c55e",
    what: "Готовит текст к печати прямо в браузере: формат A4/Letter, ориентация, поля, шрифт, колонтитулы с датой и номерами страниц. Живой предпросмотр страницы и печать через диалог браузера — без загрузки файлов на сервер.",
    why: "Быстро и опрятно распечатать заметку или документ, не открывая тяжёлый редактор.",
    example: "Вставил заметку, выбрал A4 с полями и колонтитулом → отправил на печать одной кнопкой." },
];
let aboutReady = false;
function initAbout() {
  if (aboutReady) return;
  aboutReady = true;
  const box = $("#aboutTools");
  ABOUT.forEach((t, i) => {
    const b = el("section", { class: "rblock" });
    b.style.setProperty("--tacc", t.accent);
    b.innerHTML =
      `<div class="rb-head"><div class="rb-title"><span class="dotmark"></span>` +
      `<span class="mono" style="color:var(--tacc)">0${i + 1}</span> ${esc(t.name)}</div>` +
      `<button class="act" data-nav="${t.id}">Открыть →</button></div>` +
      `<div class="rb-body">` +
      `<dl class="kv kv-wide">` +
      `<dt class="muted">Что делает</dt><dd>${esc(t.what)}</dd>` +
      `<dt class="muted">Зачем</dt><dd>${esc(t.why)}</dd>` +
      `<dt class="muted">Пример</dt><dd style="color:var(--dim)">${esc(t.example)}</dd>` +
      `</dl></div>`;
    box.append(b);
  });
}

let homeReady = false;
function initHome() {
  if (homeReady) return;
  homeReady = true;
  const grid = $("#toolGrid");
  const cards = Object.entries(TOOLS_META).map(([id, m], i) => {
    const card = el("button", { class: "tool-card", "data-nav": id });
    card.style.setProperty("--tacc", m.accent);
    const art = m.img
      ? `<img src="/brand/tools/${m.img}.png" alt="${esc(m.title)}" loading="lazy">`
      : `<span class="art-ico">${m.icon}</span>`;
    card.innerHTML =
      `<div class="art"><span class="num">0${i + 1}</span>${art}</div>` +
      `<div class="body"><h3>${esc(m.title)}</h3><p class="sub">${esc(m.sub)}</p>` +
      `<div class="tagrow">${m.tags.map((t) => `<span class="tg">${esc(t)}</span>`).join("")}</div>` +
      `<span class="go">Перейти →</span></div>`;
    return card;
  });
  grid.replaceChildren(...cards);
}

// =====================================================================
// WEB HARVESTER
// =====================================================================
$("#hvGo").addEventListener("click", runHarvester);
$("#hvUrl").addEventListener("keydown", (e) => { if (e.key === "Enter") runHarvester(); });
$("#hvReset").addEventListener("click", () => { $("#hvUrl").value = ""; $("#hvOut").replaceChildren(); $("#hvUrl").focus(); toast("Сброшено"); });

async function runHarvester() {
  const url = $("#hvUrl").value.trim();
  const out = $("#hvOut");
  if (!url) { toast("Введите URL", "error"); return; }
  await withState(out, "Загружаем и разбираем страницу…", async () => {
    const d = await api("/api/scrape/inspect", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url }),
    });
    return renderHarvest(d, url);
  });
}

// маленькие иконки для stat-cards
const ICON = {
  status: '<path d="M20 6 9 17l-5-5"/>',
  time: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  tables: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16"/>',
  entities: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  links: '<path d="M9 15 15 9M10.5 6.5 12 5a4 4 0 0 1 6 6l-1.5 1.5M13.5 17.5 12 19a4 4 0 0 1-6-6l1.5-1.5"/>',
  images: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="m4 18 5-5 4 4 3-3 4 4"/>',
  api: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M6 6l2 2M16 16l2 2M18 6l-2 2M8 16l-2 2"/>',
  words: '<path d="M4 7V5h16v2M9 5v14M7 19h4"/>',
};
function statcard(icon, value, label, cls = "") {
  return el("div", { class: `statcard ${cls}` },
    el("div", { class: "sc-ic", html: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${icon}</svg>` }),
    el("div", {}, el("div", { class: "sc-v" }, fmtNum(value)), el("div", { class: "sc-l" }, label)));
}
function rblock(titleNode, opts = {}) {
  const head = el("div", { class: "rb-head" },
    el("div", { class: "rb-title" }, el("span", { class: "dotmark" }), titleNode));
  if (opts.actions) head.append(el("div", { class: "rb-actions" }, ...opts.actions));
  const body = el("div", { class: "rb-body" });
  if (opts.note) body.append(el("div", { class: "rb-note" }, opts.note));
  const block = el("section", { class: "rblock" }, head, body);
  if (opts.accent) block.style.setProperty("--tacc", opts.accent);
  return { block, body };
}
const rbTitle = (text, count) => {
  const s = el("span", {}, text);
  if (count != null) s.append(document.createTextNode(" "), el("span", { class: "pill-count" }, count));
  return s;
};

function renderHarvest(d, url) {
  const wrap = el("div", {});
  const c = d.counts || {};
  const httpOk = d.status >= 200 && d.status < 400;

  // --- сводка: заголовок + stat-cards ---
  const sum = el("div", { class: "rblock" });
  sum.append(el("div", { class: "rb-head" },
    el("div", { class: "rb-title" }, el("span", { class: "dotmark" }), rbTitle(d.meta?.title || "Страница")),
    el("a", { class: "act plain", href: d.final_url, target: "_blank" }, "Открыть ↗")));
  const sbody = el("div", { class: "rb-body" });
  sbody.append(el("div", { class: "rb-note", style: "word-break:break-all" },
    el("span", { class: "mono" }, esc(d.final_url)), d.truncated ? " · ответ обрезан по лимиту" : ""));
  sbody.append(el("div", { class: "statgrid" },
    statcard(ICON.status, `${d.status}`, "HTTP-статус", httpOk ? "ok" : "alert"),
    statcard(ICON.time, `${Math.round(d.elapsed_ms)} мс`, "время ответа"),
    statcard(ICON.tables, c.tables || 0, "таблиц"),
    statcard(ICON.entities, (d.entities || []).length, "сущностей"),
    statcard(ICON.links, c.links || 0, "ссылок"),
    statcard(ICON.images, c.images || 0, "картинок"),
    statcard(ICON.api, (d.api_candidates || []).length, "API-кандидатов"),
    statcard(ICON.words, c.words || 0, "слов")));
  sum.append(sbody);
  wrap.append(sum);

  // --- таблицы ---
  if (d.tables?.length) {
    const { block, body } = rblock(rbTitle("Таблицы", d.tables.length), { accent: "#22d3ee" });
    d.tables.forEach((t) => {
      body.append(el("div", { class: "ent" },
        el("div", { class: "ent-top" },
          el("div", { class: "ent-meta" },
            el("strong", {}, `#${t.index}`), t.caption ? el("span", {}, esc(t.caption)) : null,
            el("span", { class: "muted" }, `${fmtNum(t.rows)} строк × ${t.columns} колонок`)),
          el("div", { class: "rb-actions" },
            actBtn("↓ CSV", `/api/scrape/extract?url=${encodeURIComponent(url)}&target=tables&index=${t.index}&format=csv`),
            actBtn("↓ JSON", `/api/scrape/extract?url=${encodeURIComponent(url)}&target=tables&index=${t.index}&format=json`))),
        dtable(t.headers, t.preview)));
    });
    wrap.append(block);
  }

  // --- повторяющиеся сущности (инспекция) ---
  if (d.entities?.length) {
    const { block, body } = rblock(rbTitle("Повторяющиеся сущности", d.entities.length),
      { accent: "#a855f7", note: "Эвристика: найденные карточки одинаковой структуры. Любую группу можно собрать в датасет." });
    d.entities.forEach((g, i) => {
      const conf = Math.round((g.confidence || 0) * 100);
      body.append(el("div", { class: "ent" },
        el("div", { class: "ent-top" },
          el("div", { class: "ent-meta" },
            el("code", { class: "mono" }, esc(g.signature)),
            sevBadge("info", `${g.count} шт`),
            el("span", {}, `поля: ${esc(g.fields.join(", "))}`),
            el("span", { title: "достоверность" }, el("span", { class: "meter" }, el("i", { style: `width:${conf}%` })), ` ${conf}%`)),
          el("div", { class: "rb-actions" },
            actBtn("⤓ Build Dataset · CSV", `/api/scrape/build-dataset?url=${encodeURIComponent(url)}&group=${i}&format=csv`),
            actBtn("JSONL", `/api/scrape/build-dataset?url=${encodeURIComponent(url)}&group=${i}&format=ndjson`))),
        dtableEntities(g.fields, g.preview)));
    });
    wrap.append(block);
  }

  // --- API-кандидаты ---
  if (d.api_candidates?.length) {
    const { block, body } = rblock(rbTitle("Кандидаты в API", d.api_candidates.length),
      { accent: "#fb7132", note: "Найдены в HTML/JS/ссылках страницы. XHR у SPA сервер не исполняет и не видит." });
    d.api_candidates.slice(0, 20).forEach((cand) => {
      body.append(el("div", { class: "cand" },
        sevBadge(cand.confidence === "high" ? "ok" : cand.confidence === "medium" ? "warn" : "info", cand.confidence),
        el("code", {}, esc(cand.url)),
        el("button", { class: "act", onclick: () => openInFinder(cand.url) }, "→ API Finder")));
    });
    wrap.append(block);
  }

  // --- метаданные ---
  if (d.meta) {
    const m = d.meta;
    const rows = [["Заголовок", m.title], ["Описание", m.description], ["Canonical", m.canonical], ["Язык", m.lang]].filter(([, v]) => v);
    if (rows.length) {
      const { block, body } = rblock(rbTitle("Метаданные"), { accent: "#3b82f6" });
      body.append(el("dl", { class: "kv kv-wide" },
        ...rows.flatMap(([k, v]) => [el("dt", { class: "muted" }, k), el("dd", {}, esc(v))])));
      wrap.append(block);
    }
  }

  if (!d.tables?.length && !d.entities?.length && !d.api_candidates?.length) {
    wrap.append(el("div", { class: "state" }, el("div", { class: "ico" }, "🦊"),
      "Структурированных данных не нашлось. Так бывает на страницах без таблиц и регулярной разметки."));
  }
  return wrap;
}
const actBtn = (label, href) => el("a", { class: "act", href, target: "_blank" }, label);

function dtable(headers, rows) {
  const w = el("div", { class: "dtable-wrap", style: "margin-top:6px" });
  const table = el("table", { class: "dtable" });
  table.append(el("thead", {}, el("tr", {}, ...(headers || []).map((h) => el("th", {}, esc(h))))));
  const tb = el("tbody", {});
  (rows || []).slice(0, 6).forEach((r) => tb.append(el("tr", {}, ...r.map((cell) => el("td", { title: cell || "" }, esc(cell))))));
  table.append(tb);
  w.append(table);
  return w;
}
function dtableEntities(fields, items) {
  const cols = fields.length ? fields : ["title", "text"];
  return dtable(cols, (items || []).map((it) => cols.map((c) => it[c] || "")));
}

async function openInFinder(url) {
  navigate("finder");
  const out = $("#afOut");
  await withState(out, "Опознаём API…", async () => {
    const d = await api("/api/apifinder/check-url", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url }),
    });
    if (d.match === "catalog") return el("div", { class: "result-cards" }, apiCard(d));
    return el("div", { class: "panel" },
      el("h3", {}, "Кандидат найден, но не в каталоге"),
      el("p", { class: "muted" }, d.note || ""),
      el("div", { class: "kv" }, el("dt", {}, "URL"), el("dd", {}, el("code", { class: "mono" }, esc(d.url)))),
      el("div", { style: "margin-top:12px" }, sevBadge("info", "discovered")));
  });
}

const chipCount = (label, n) => el("span", { class: "chip" }, `${label}: ${fmtNum(n || 0)}`);
const dlBtn = (label, href) => el("a", { class: "btn sm ghost", href, target: "_blank", style: "margin-left:6px;display:inline-flex;align-items:center" }, `↓ ${label}`);

function previewTable(headers, rows) {
  const wrap = el("div", { class: "table-wrap", style: "margin-top:8px" });
  const table = el("table", { class: "data" });
  table.append(el("thead", {}, el("tr", {}, ...(headers || []).map((h) => el("th", {}, esc(h))))));
  const tb = el("tbody", {});
  (rows || []).slice(0, 5).forEach((r) => tb.append(el("tr", {}, ...r.map((cell) => el("td", {}, esc(cell))))));
  table.append(tb);
  wrap.append(table);
  return wrap;
}
function previewEntities(fields, items) {
  const cols = fields.length ? fields : ["title", "text"];
  return previewTable(cols, (items || []).map((it) => cols.map((c) => it[c] || "")));
}

// =====================================================================
// API FINDER
// =====================================================================
let finderReady = false;
function loadFav() { try { return JSON.parse(localStorage.getItem("forit-fav") || "[]"); } catch { return []; } }
function saveFav(ids) { try { localStorage.setItem("forit-fav", JSON.stringify(ids)); } catch {} $("#afFavCount").textContent = ids.length; }
function toggleFav(id) {
  const fav = loadFav();
  const i = fav.indexOf(id);
  if (i >= 0) { fav.splice(i, 1); toast("Убрано из избранного"); } else { fav.push(id); toast("Сохранено в избранное", "success"); }
  saveFav(fav);
}

async function initFinderOnce() {
  if (finderReady) return;
  finderReady = true;
  saveFav(loadFav());
  try {
    const cats = await api("/api/apifinder/categories");
    const box = $("#afCats");
    box.append(el("span", { class: "chip active", "data-cat": "", onclick: (e) => selectCat(e.target, "") }, "Все"));
    Object.entries(cats).forEach(([name, n]) =>
      box.append(el("span", { class: "chip", "data-cat": name, onclick: (e) => selectCat(e.target, name) }, `${name} (${n})`)));
  } catch {}
  runFinderSearch();
}
function selectCat(node, cat) {
  $$("#afCats .chip").forEach((c) => c.classList.toggle("active", c === node));
  runFinderSearch(cat);
}
$("#afSearch").addEventListener("click", () => runFinderSearch());
$("#afQuery").addEventListener("keydown", (e) => { if (e.key === "Enter") runFinderSearch(); });
["afNoKey", "afOpenData", "afFreeTier", "afCors"].forEach((id) => $("#" + id).addEventListener("change", () => runFinderSearch()));
$("#afSurprise").addEventListener("click", runSurprise);
$("#afExplore").addEventListener("click", runExplore);
$("#afFav").addEventListener("click", runFavorites);
$("#afReset").addEventListener("click", () => {
  $("#afQuery").value = "";
  ["afNoKey", "afOpenData", "afFreeTier", "afCors"].forEach((id) => ($("#" + id).checked = false));
  $$("#afCats .chip").forEach((c) => c.classList.toggle("active", c.dataset.cat === ""));
  runFinderSearch("");
  toast("Фильтры сброшены");
});

function activeCat() { return $("#afCats .chip.active")?.dataset.cat || ""; }

async function runFinderSearch(cat = activeCat()) {
  const out = $("#afOut");
  const params = new URLSearchParams();
  const q = $("#afQuery").value.trim();
  if (q) params.set("q", q);
  if (cat) params.set("category", cat);
  if ($("#afNoKey").checked) params.set("no_key", "true");
  if ($("#afOpenData").checked) params.set("free_type", "open_data");
  else if ($("#afFreeTier").checked) params.set("free_type", "free_tier");
  if ($("#afCors").checked) params.set("cors", "true");
  await withState(out, "Ищем API…", async () => {
    const d = await api("/api/apifinder/search?" + params.toString());
    if (!d.results.length) return State.empty("Под эти условия ничего нет. Смягчите фильтры.");
    return el("div", {},
      el("div", { class: "muted", style: "margin-bottom:12px" }, `Найдено: ${d.count}`),
      el("div", { class: "result-cards" }, ...d.results.map(apiCard)));
  });
}

async function runSurprise() {
  const out = $("#afOut");
  await withState(out, "Подбираем связку…", async () => {
    const d = await api("/api/apifinder/surprise");
    return el("div", {},
      el("div", { class: "panel" }, el("h3", {}, "🎲 Идея проекта"), el("p", {}, d.idea),
        el("div", { class: "muted" }, "Пайплайн: " + (d.workflow || ""))),
      el("div", { class: "result-cards" }, ...d.apis.map(apiCard)));
  });
}

async function runExplore() {
  const out = $("#afOut");
  await withState(out, "Загружаем темы…", async () => {
    const d = await api("/api/apifinder/explore");
    return el("div", { class: "panel" },
      el("h3", {}, "💡 С чего начать"),
      el("div", { class: "chips" }, ...d.topics.map((t) =>
        el("span", { class: "chip", onclick: () => exploreTopic(t.id) }, t.title))));
  });
}
async function exploreTopic(id) {
  const out = $("#afOut");
  await withState(out, "Подбираем…", async () => {
    const d = await api("/api/apifinder/explore/" + encodeURIComponent(id));
    return el("div", { class: "result-cards" }, ...d.results.map(apiCard));
  });
}

async function runFavorites() {
  const out = $("#afOut");
  const fav = loadFav();
  if (!fav.length) { render(out, State.empty("В избранном пусто. Жми ★ на карточках.")); return; }
  await withState(out, "Загружаем избранное…", async () => {
    const d = await api("/api/apifinder/favorites/export?ids=" + encodeURIComponent(fav.join(",")));
    const head = el("div", { class: "list-head" },
      el("div", { class: "muted" }, `В избранном: ${d.count}`),
      el("a", { class: "btn sm", href: "/api/apifinder/favorites/export?format=csv&ids=" + encodeURIComponent(fav.join(",")), target: "_blank" }, "↓ Экспорт CSV"));
    return el("div", {}, head, el("div", { class: "result-cards" }, ...d.favorites.map(apiCard)));
  });
}

const STATUS_LABEL = {
  docs_verified: ["ok", "по документации"],
  availability_checked: ["ok", "доступность подтверждена"],
  discovered: ["info", "найден, не проверен"],
  stale: ["warn", "давно не проверяли"],
};
const FREE_LABEL = { free_forever: "бесплатно навсегда", free_tier: "free tier", open_data: "open data" };

function apiCard(a) {
  const [sev, label] = STATUS_LABEL[a.status] || ["info", a.status];
  const fav = loadFav().includes(a.id);
  const card = el("div", { class: "rcard" },
    el("div", { class: "rhead" },
      el("div", {}, el("h4", {}, a.name), el("div", { class: "cat" }, a.category)),
      sevBadge(sev, label)),
    el("div", { class: "desc" }, a.description),
    el("dl", { class: "kv" },
      kv("Ключ", a.no_key ? "не нужен" : a.auth === "key" ? "нужен (бесплатный)" : a.auth),
      kv("Тип", FREE_LABEL[a.free_type] || a.free_type),
      kv("Лимит", a.request_limit),
      kv("Rate limit", a.rate_limit),
      kv("Коммерция", a.commercial_use),
      kv("CORS", a.cors ? "да" : "нет"),
      kv("Форматы", (a.formats || []).join(", ")),
      kv("Источник", a.source),
      kv("Проверено", a.last_verified_at || "—")),
    a.why_useful ? el("div", { class: "why" }, a.why_useful) : null,
    (a.project_ideas && a.project_ideas.length) ? el("div", { class: "muted" }, "Идеи: " + a.project_ideas.join(" · ")) : null,
    el("div", { class: "actions" },
      a.docs_url ? el("a", { class: "btn sm ghost", href: a.docs_url, target: "_blank" }, "Документация") : null,
      el("button", { class: "btn sm ghost", onclick: () => checkApi(a.id, card) }, "Проверить доступность"),
      a.actions?.example_request ? el("a", { class: "btn sm ghost", href: a.actions.example_request, target: "_blank" }, "Пример запроса") : null,
      el("button", { class: "btn sm" + (fav ? "" : " ghost"), onclick: (e) => { toggleFav(a.id); e.target.classList.toggle("ghost"); } }, "★")));
  return card;
}
function kv(k, v) {
  const frag = document.createDocumentFragment();
  frag.append(el("dt", {}, k), el("dd", {}, esc(v ?? "—")));
  return frag;
}

async function checkApi(id, card) {
  toast("Проверяем доступность…");
  try {
    const d = await api(`/api/apifinder/apis/${encodeURIComponent(id)}/check`);
    const av = d.availability || {};
    toast(av.ok ? `Доступен: ${av.status}, ${av.elapsed_ms} мс` : `Недоступен: ${av.reason || av.status || "?"}`, av.ok ? "success" : "error");
  } catch (e) {
    toast(e.message, "error");
  }
}

// =====================================================================
// DATA BURNER
// =====================================================================
let burnerReady = false;
let burnerPresets = [];
async function initBurnerOnce() {
  if (burnerReady) return;
  burnerReady = true;
  try {
    burnerPresets = await api("/api/burner/presets");
    const sel = $("#buPreset");
    burnerPresets.forEach((p) => sel.append(el("option", { value: p.id }, p.id)));
    const showDesc = () => { const p = burnerPresets.find((x) => x.id === sel.value); $("#buPresetDesc").textContent = p ? p.description : ""; };
    sel.addEventListener("change", showDesc);
    showDesc();
  } catch (e) { toast(e.message, "error"); }
}
function burnerParams() {
  const p = new URLSearchParams({ preset: $("#buPreset").value, rows: $("#buRows").value, format: $("#buFormat").value });
  if ($("#buSeed").value) p.set("seed", $("#buSeed").value);
  return p;
}
$("#buReset").addEventListener("click", () => {
  const sel = $("#buPreset"); if (sel.options.length) sel.selectedIndex = 0;
  sel.dispatchEvent(new Event("change"));
  $("#buRows").value = "1000"; $("#buFormat").value = "csv"; $("#buSeed").value = "";
  $("#buOut").replaceChildren(); toast("Сброшено");
});
$("#buGen").addEventListener("click", () => {
  window.open("/api/burner/datasets?" + burnerParams().toString(), "_blank");
  toast("Файл скачивается…", "success");
});
$("#buPreview").addEventListener("click", async () => {
  const out = $("#buOut");
  const p = burnerParams(); p.set("download", "false");
  await withState(out, "Генерируем…", async () => {
    const text = await api("/api/burner/datasets?" + p.toString());
    return el("div", { class: "panel" }, el("h3", {}, "Предпросмотр"), el("pre", { class: "code" }, text.slice(0, 4000)));
  });
});
$("#buPair").addEventListener("click", async () => {
  const p = new URLSearchParams({ preset: $("#buPreset").value, rows: $("#buRows").value });
  if ($("#buSeed").value) p.set("seed", $("#buSeed").value);
  toast("Собираем пару и сравниваем…");
  try {
    const pair = await api("/api/burner/pair?" + p.toString());
    navigate("drift");
    const out = $("#drOut");
    await withState(out, "Сравниваем сгенерированную пару…", async () => {
      const rep = await api("/api/drift/compare", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ reference: pair.reference, current: pair.current, save: false }),
      });
      return renderDrift(rep);
    });
  } catch (e) { toast(e.message, "error"); }
});

// =====================================================================
// DRIFT LAB
// =====================================================================
$("#drGo").addEventListener("click", async () => {
  const ref = $("#drRef").files[0], cur = $("#drCur").files[0];
  if (!ref || !cur) { toast("Выберите оба файла", "error"); return; }
  const fd = new FormData();
  fd.append("reference", ref); fd.append("current", cur);
  await withState($("#drOut"), "Сравниваем выгрузки…", async () => {
    const rep = await api("/api/drift/reports?save=false", { method: "POST", body: fd });
    return renderDrift(rep);
  });
});
$("#drReset").addEventListener("click", () => {
  $("#drRef").value = ""; $("#drCur").value = ""; $("#drOut").replaceChildren(); toast("Сброшено");
});
$("#drDemo").addEventListener("click", async () => {
  await withState($("#drOut"), "Прогоняем демо…", async () => renderDrift(await api("/api/drift/demo")));
});

function renderDrift(rep) {
  const s = rep.summary || {};
  const wrap = el("div", {});
  wrap.append(el("div", { class: `verdict ${s.status}` },
    el("span", { class: "big" }, MARK[s.status] || "•"),
    el("span", {}, s.verdict || "")));

  wrap.append(el("div", { class: "panel" }, el("h3", {}, "Итог"),
    el("div", { class: "chips" },
      el("span", { class: "chip" }, `строк: ${fmtNum(rep.rows?.reference)} → ${fmtNum(rep.rows?.current)}`),
      el("span", { class: "chip" }, `критичных: ${s.alerts}`),
      el("span", { class: "chip" }, `заметных: ${s.warnings}`),
      el("span", { class: "chip" }, `колонок: ${s.columns_analyzed}`))));

  // что это значит для разработчика
  wrap.append(driftExplain(rep, s));

  // схема
  const sc = rep.schema || {};
  if (sc.added?.length || sc.removed?.length || sc.type_changed?.length) {
    const p = el("div", { class: "panel" }, el("h3", {}, "Схема"));
    sc.added.forEach((c) => p.append(finding("warn", c, "новая колонка")));
    sc.removed.forEach((c) => p.append(finding("alert", c, "колонка исчезла")));
    sc.type_changed.forEach((t) => p.append(finding("alert", t.column, `тип: ${t.from} → ${t.to}`)));
    wrap.append(p);
  }

  // распределения (PSI)
  const drifting = (rep.columns || []).filter((c) => c.metrics && c.metrics.psi != null);
  if (drifting.length) {
    drifting.sort((a, b) => (b.metrics.psi || 0) - (a.metrics.psi || 0));
    const tbl = el("table", { class: "data stack" }, el("thead", {}, el("tr", {},
      el("th", {}, "Колонка"), el("th", {}, "Анализ"), el("th", { class: "num" }, "PSI"), el("th", { class: "num" }, "KS"), el("th", {}, "Статус"))));
    const tb = el("tbody", {});
    drifting.forEach((c) => tb.append(el("tr", {},
      el("td", { class: "st-title" }, c.column), el("td", { class: "muted", "data-label": "Анализ" }, c.analysis),
      el("td", { class: "num", "data-label": "PSI" }, (c.metrics.psi ?? "").toString()),
      el("td", { class: "num", "data-label": "KS" }, c.metrics.ks_statistic != null ? c.metrics.ks_statistic : "—"),
      el("td", { "data-label": "Статус" }, sevBadge(c.status)))));
    tbl.append(tb);
    wrap.append(el("div", { class: "panel" }, el("h3", {}, "Распределения"), el("div", { class: "table-wrap stack-wrap" }, tbl)));
  }

  // все находки
  const all = [];
  (sc.findings || []).forEach((f) => all.push(["schema", f]));
  (rep.columns || []).forEach((c) => (c.findings || []).forEach((f) => all.push([c.column, f])));
  if (all.length) {
    const p = el("div", { class: "panel" }, el("h3", {}, "Находки ", el("span", { class: "pill-count" }, all.length)));
    all.sort((a, b) => ({ alert: 3, warn: 2, info: 1, ok: 0 }[b[1].severity] - { alert: 3, warn: 2, info: 1, ok: 0 }[a[1].severity]));
    all.forEach(([col, f]) => p.append(finding(f.severity, col, f.message)));
    wrap.append(p);
  }
  return wrap;
}
const finding = (sev, col, msg) => el("div", { class: "finding" },
  el("span", { class: `mk ${sev}` }, MARK[sev] || "•"),
  el("span", { class: "col" }, col), el("span", { style: "flex:1" }, msg));

// человеческий разбор drift-отчёта: что это значит и что делать
function driftExplain(rep, s) {
  const sc = rep.schema || {};
  const cols = (list) => {
    const u = [...new Set(list)];
    return u.slice(0, 5).join(", ") + (u.length > 5 ? ` и ещё ${u.length - 5}` : "");
  };
  const byCode = {};
  (rep.columns || []).forEach((c) => (c.findings || []).forEach((f) => {
    (byCode[f.code] = byCode[f.code] || []).push(c.column);
  }));
  const has = (code) => (byCode[code] || []).length;
  const adv = [];

  if (sc.removed?.length)
    adv.push(["alert", `Исчезли колонки: ${cols(sc.removed)}. Это ломающее изменение схемы — код, запросы и дашборды, которые их читают, упадут. Договорись с источником или заведи data-contract.`]);
  if (sc.type_changed?.length)
    adv.push(["alert", `Сменился тип у: ${cols(sc.type_changed.map((t) => t.column))}. Строгий загрузчик/парсер начнёт падать или молча портить данные — поправь приведение типов в ETL.`]);
  if (sc.added?.length)
    adv.push(["warn", `Новые колонки: ${cols(sc.added)}. Ничего не сломается, но их никто не обрабатывает — добавь их в обработку или явно игнорируй.`]);

  if (has("missing.appeared") || has("missing.rate_change"))
    adv.push(["alert", `Резко выросли пропуски: ${cols([...(byCode["missing.appeared"] || []), ...(byCode["missing.rate_change"] || [])])}. Чаще это сбой выгрузки на стороне источника, а не реальное изменение данных — проверь пайплайн экспорта.`]);

  const distCols = [...new Set([...(byCode["distribution.psi"] || []), ...(byCode["distribution.ks"] || []), ...(byCode["distribution.mean_shift"] || []), ...(byCode["category.psi"] || []), ...(byCode["category.chi_square"] || [])])];
  if (distCols.length)
    adv.push(["warn", `Распределение уехало: ${cols(distCols)}. Если на этих данных обучена модель — пора переобучать; заодно проверь, не сменились ли единицы измерения или источник.`]);

  if (has("category.new"))
    adv.push(["warn", `Появились новые категории: ${cols(byCode["category.new"])}. Обнови справочники и энкодеры — иначе модель/валидация встретят незнакомое значение.`]);
  if (has("quality.became_constant"))
    adv.push(["alert", `Схлопнулись в константу: ${cols(byCode["quality.became_constant"])}. Скорее всего поле перестало заполняться на источнике.`]);
  if (has("quality.mixed_types"))
    adv.push(["warn", `Появились смешанные типы: ${cols(byCode["quality.mixed_types"])}. В одну колонку попадают значения разного вида — проверь парсинг на источнике.`]);
  if (has("leakage.identifier_overlap"))
    adv.push(["alert", `Идентификаторы пересекаются между выгрузками: ${cols(byCode["leakage.identifier_overlap"])}. Это одна и та же выборка или утечка train/test — для честной валидации так нельзя.`]);

  const ch = rep.rows?.change;
  if (ch != null && Math.abs(ch) >= 0.25)
    adv.push(["info", `Число строк изменилось на ${(ch * 100).toFixed(0)}%. Проверь полноту выгрузки — не обрезалась ли она и не задвоилась ли.`]);

  if (!adv.length)
    adv.push(["ok", "Значимых расхождений нет — схема и распределения стабильны, можно катить дальше без переобучения."]);

  const { block, body } = rblock(rbTitle("Что это значит"), { accent: "#3b82f6" });
  body.append(el("div", { class: "rb-note", style: "margin-top:0" },
    "Короткий разбор в терминах твоего пайплайна — что происходит и что делать:"));
  adv.forEach(([sev, msg]) => body.append(finding(sev, "", msg)));
  return block;
}

// =====================================================================
// UNICODE CRIME LAB
// =====================================================================
let unicodeReady = false;
async function initUnicodeOnce() {
  if (unicodeReady) return;
  unicodeReady = true;
  try {
    const samples = await api("/api/unicode/samples");
    const sel = $("#unSample");
    samples.forEach((s) => sel.append(el("option", { value: s.text }, `${s.id} — ${s.problem}`)));
    sel.addEventListener("change", () => { if (sel.value) { $("#unText").value = sel.value; runUnicode(); } });
  } catch {}
}
$("#unGo").addEventListener("click", runUnicode);
$("#unReset").addEventListener("click", () => {
  $("#unText").value = ""; $("#unSample").selectedIndex = 0; $("#unOut").replaceChildren(); $("#unText").focus(); toast("Сброшено");
});
async function runUnicode() {
  const text = $("#unText").value;
  if (!text) { toast("Вставьте текст", "error"); return; }
  await withState($("#unOut"), "Анализируем символы…", async () => {
    const d = await api("/api/unicode/inspect", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }),
    });
    return renderUnicode(text, d);
  });
}
function renderUnicode(text, d) {
  const wrap = el("div", {});
  wrap.append(el("div", { class: `verdict ${d.status}` },
    el("span", { class: "big" }, MARK[d.status] || "•"),
    el("span", {}, d.status === "ok" ? "Подозрительного не найдено" : "Найдены проблемные символы")));

  // подсветка
  const issueByIndex = {};
  (d.issues || []).forEach((i) => (issueByIndex[i.index] = i));
  const render = el("div", { class: "uni-render" });
  [...text].forEach((ch, i) => {
    const iss = issueByIndex[i];
    if (iss) {
      const shown = ch.trim() === "" || !ch.match(/\P{C}/u) ? `[${iss.codepoint}]` : ch;
      render.append(el("span", { class: `uni-mark ${iss.severity}`, title: `${iss.codepoint} ${iss.name} — ${iss.note}` }, shown));
    } else {
      render.append(document.createTextNode(ch));
    }
  });
  wrap.append(el("div", { class: "panel" }, el("h3", {}, "Текст с подсветкой"), render,
    el("div", { class: "muted", style: "margin-top:8px" }, "Наведи на подсвеченный символ — покажет код и в чём проблема.")));

  // очищенная строка + копирование
  const cleaned = d.cleaned?.text ?? text;
  const changed = d.cleaned?.changed;
  const cleanInput = el("input", { type: "text", readonly: "", value: cleaned, style: "font-family:var(--mono)" });
  const copyBtn = el("button", { class: "btn sm" }, "Копировать");
  copyBtn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(cleaned); }
    catch { cleanInput.select(); document.execCommand("copy"); }
    toast("Очищенная строка скопирована", "success");
  });
  const { block: cblock, body: cbody } = rblock(rbTitle("Очищенная строка"), { accent: "#c084fc" });
  cbody.append(
    el("div", { class: "rb-note", style: "margin-top:0" },
      changed ? "Убраны невидимые символы и мягкие переносы, экзотические пробелы → обычный, приведено к NFC. Гомоглифы помечены выше, но не заменяются автоматически (это было бы потерей данных)." : "Строка уже чистая — копия совпадает с оригиналом."),
    el("div", { class: "copy-row" }, cleanInput, copyBtn));
  wrap.append(cblock);

  // находки
  if (d.findings?.length) {
    const p = el("div", { class: "panel" }, el("h3", {}, "Находки"));
    d.findings.forEach((f) => p.append(finding(f.severity, "", f.message)));
    wrap.append(p);
  }

  // нормализация
  const n = d.normalization || {};
  wrap.append(el("div", { class: "panel" }, el("h3", {}, "Нормализация"),
    el("div", { class: "chips" },
      el("span", { class: `chip ${n.is_nfc ? "active" : ""}` }, n.is_nfc ? "уже в NFC ✓" : "не в NFC ✕"),
      el("span", { class: "chip" }, `символов: ${d.length?.characters}`),
      el("span", { class: "chip" }, `байт: ${d.length?.bytes}`)),
    d.cleaned?.changed ? el("div", { style: "margin-top:10px" }, el("span", { class: "muted" }, "После очистки: "), el("code", { class: "mono" }, esc(d.cleaned.text))) : el("div", { class: "muted" }, "Очистка ничего не меняет — строка чистая.")));
  return wrap;
}

// =====================================================================
// CHAOS API
// =====================================================================
["chStatus", "chDelay", "chBody", "chFail", "chHostile"].forEach((id) => $("#" + id).addEventListener("input", buildChaosUrl));
function buildChaosUrl() {
  const p = new URLSearchParams({
    status: $("#chStatus").value || "200",
    delay_ms: $("#chDelay").value || "0",
    body: $("#chBody").value,
  });
  const fail = parseFloat($("#chFail").value);
  if (fail > 0) p.set("fail_rate", String(fail));
  if ($("#chHostile").checked) p.set("hostile_headers", "true");
  const url = `${location.origin}/api/chaos/respond?${p.toString()}`;
  $("#chUrl").value = url;
  return url;
}
$("#chCopy").addEventListener("click", async () => {
  const url = $("#chUrl").value;
  try { await navigator.clipboard.writeText(url); toast("URL скопирован", "success"); }
  catch { $("#chUrl").select(); document.execCommand("copy"); toast("URL скопирован", "success"); }
});
$("#chReset").addEventListener("click", () => {
  $("#chStatus").value = "503"; $("#chDelay").value = "2000"; $("#chBody").value = "json";
  $("#chFail").value = "0"; $("#chHostile").checked = false; $("#chOut").replaceChildren();
  buildChaosUrl(); toast("Сброшено");
});
$("#chTry").addEventListener("click", async () => {
  const url = buildChaosUrl();
  await withState($("#chOut"), "Отправляем запрос…", async () => {
    const started = performance.now();
    let res, bodyText;
    try { res = await fetch(url); bodyText = await res.text(); }
    catch (e) { throw new ApiError("Запрос оборвался (возможно, так и задумано)", String(e)); }
    const ms = Math.round(performance.now() - started);
    const headers = [...res.headers.entries()].map(([k, v]) => `${k}: ${v}`).join("\n");
    const panel = el("div", { class: "panel" },
      el("h3", {}, `Ответ: ${res.status} · ${ms} мс`),
      el("h4", {}, "Заголовки"), el("pre", { class: "code" }, headers || "—"),
      el("h4", {}, "Тело"), el("pre", { class: "code" }, bodyText.slice(0, 4000) || "(пусто)"));
    // что это значит для разработчика
    const ctype = res.headers.get("content-type") || "";
    let jsonBroke = false;
    if (bodyText && ctype.includes("json")) { try { JSON.parse(bodyText); } catch { jsonBroke = true; } }
    const advice = [];
    if (res.status >= 500) advice.push(["alert", `Сервер отдал ${res.status}. В клиенте: покажи понятную ошибку (не белый экран), заложи ретрай с экспоненциальным backoff и уважай Retry-After.`]);
    else if (res.status >= 400) advice.push(["warn", `Клиентская ошибка ${res.status}. Такое не стоит ретраить вслепую — разбери причину и покажи пользователю, что не так.`]);
    else advice.push(["ok", `Статус ${res.status} — успех. Но проверь, что клиент не считает успехом любой ответ, не глядя на код.`]);
    if (ms >= 1500) advice.push(["warn", `Ответ шёл ${ms} мс. Есть ли у запроса таймаут? Показываешь ли индикатор загрузки? Не блокируется ли UI?`]);
    if (jsonBroke) advice.push(["alert", "Тело не парсится как JSON, хотя Content-Type обещает JSON. Оборачивай JSON.parse в try/catch и не доверяй заголовку слепо."]);
    if ($("#chBody").value === "huge") advice.push(["warn", "Гигантское тело. Не тяни весь ответ в память — стримь, ставь лимит размера."]);
    if ($("#chHostile").checked) advice.push(["warn", "Враждебные заголовки: Retry-After может быть не числом, X-Total-Count — мусором. Валидируй заголовки перед использованием."]);
    if (parseFloat($("#chFail").value) > 0) advice.push(["info", "Плавающие сбои: нужна идемпотентность запросов и разумные ретраи, иначе повтор создаст дубли."]);
    const { block, body } = rblock(rbTitle("Что это значит для разработчика"), { accent: "#f43f5e" });
    advice.forEach(([sev, msg]) => body.append(finding(sev, "", msg)));
    return el("div", {}, panel, block);
  });
});

// ---------- старт (перенесён в конец файла, после всех определений) ----------

// =====================================================================
// WEB PARSER (субфаза 1a: INPUT → INSPECT). Режимы Extract/Crawl/Audit
// появятся в следующих субфазах — сейчас показываем честную заглушку.
// =====================================================================
let parserReady = false;
const PA_MODE_NOTE = {
  extract: "Достаёт повторяющиеся данные (карточки, строки) в таблицу: находит источник, предлагает поля, даёт превью и экспорт CSV/JSON. Кнопка «Собрать все страницы» пройдёт пагинацию каталога.",
  crawl: "Обходит сайт по внутренним ссылкам и строит карту страниц: коды ответов, редиректы, битые ссылки. По умолчанию не больше 50 страниц.",
  audit: "Технический аудит по страницам сайта: title, description, H1, коды ответов и битые ссылки. По умолчанию не больше 50 страниц.",
  explore: "Ручной HTTP-запрос как в Postman: метод, заголовки, тело — для отладки и не-GET. Обычный сбор данных — во вкладке Extract.",
};
let paMode = "extract";
const paState = { input: "", base_url: "", schema: null };
async function initParserOnce() {
  if (parserReady) return;
  parserReady = true;
  try {
    const b = await api("/api/parser/backend");
    $("#paBackend").textContent = `backend: ${b.backend}${b.css ? " · css" : ""}${b.xpath ? " · xpath" : ""}`;
  } catch {}
  $("#paGo").addEventListener("click", runParserGo);
  $("#paReset").addEventListener("click", () => { $("#paInput").value = ""; $("#paOut").replaceChildren(); paState.schema = null; $("#paInput").focus(); toast("Сброшено"); });
  $$("#paModes .pa-mode").forEach((btn) => btn.addEventListener("click", () => selectParserMode(btn.dataset.mode)));
  selectParserMode(paMode);  // показать пояснение активного режима сразу при входе
}
function selectParserMode(mode) {
  const changed = mode !== paMode;
  paMode = mode;
  $$("#paModes .pa-mode").forEach((b) => {
    const on = b.dataset.mode === mode;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
  });
  // Пояснение активного режима — показываем всегда, а не только для «дорожной карты».
  const note = $("#paModeNote");
  const txt = PA_MODE_NOTE[mode] || "";
  note.style.display = txt ? "" : "none";
  note.textContent = txt;
  // Смена режима: останавливаем текущий обход/сбор (чтобы не грузил сервер зря)
  // и очищаем чужой результат — можно сразу запустить другое.
  if (changed) {
    stopActiveParserJobs();
    $("#paOut").replaceChildren();
  }
}

// Отменяет активные фоновые задачи Parser при СМЕНЕ режима. Best-effort.
// Обнуляем ссылки — pump увидит paCrawl!==job и тихо выйдет, не рисуя чужой финал
// в уже очищенный вывод (в отличие от кнопки «Отменить», где показываем «отменён»).
function stopActiveParserJobs() {
  if (paCrawl) {
    api(`/api/parser/crawl/${paCrawl.job_id}/cancel`, { method: "POST" }).catch(() => {});
    paCrawl = null;
  }
  if (paCollect) {
    api(`/api/parser/collect/${paCollect.job_id}/cancel`, { method: "POST" }).catch(() => {});
    paCollect = null;
  }
}
// paGo диспетчеризует по активному режиму: Extract → сбор данных, Explore → разбор
async function runParserGo() {
  if (paMode === "extract") return runParserExtract();
  if (paMode === "crawl" || paMode === "audit") return runCrawl(paMode);
  return runParserExplore();
}
async function runParserInspect() {
  const input = $("#paInput").value.trim();
  const out = $("#paOut");
  if (!input) { toast("Вставьте URL, HTML, JSON или curl", "error"); return; }
  selectParserMode("explore");
  await withState(out, "Определяем источник…", async () => {
    const d = await api("/api/parser/inspect", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input }),
    });
    return renderParserInspect(d);
  });
}
function renderParserInspect(d) {
  const wrap = el("div", {});
  if (d.error) return State.error(new ApiError(d.error, d.detail));

  // сводка: вид ввода + тип источника
  const chips = el("div", { class: "chips", style: "margin-bottom:14px" },
    el("span", { class: "chip active" }, `ввод: ${d.input?.kind || "?"}`),
    d.source_type ? el("span", { class: "chip" }, `источник: ${d.source_type}`) : null,
    d.backend ? el("span", { class: "chip" }, `backend: ${d.backend.backend}`) : null);
  wrap.append(chips);

  (d.notes || []).forEach((n) => wrap.append(el("div", { class: "rb-note", style: "margin-top:0" }, n)));

  // разобранный запрос (для cURL)
  if (d.request) {
    const { block, body } = rblock(rbTitle("Разобранный запрос"), { accent: "#a855f7" });
    body.append(el("pre", { class: "code" }, JSON.stringify(d.request, null, 2)));
    wrap.append(block);
  }

  // ответ (для URL)
  if (d.response) {
    const r = d.response;
    const { block, body } = rblock(rbTitle("Ответ"), { accent: "#22d3ee" });
    body.append(el("div", { class: "statgrid" },
      statcard(ICON.status, `${r.status}`, "HTTP", r.status < 400 ? "ok" : "alert"),
      statcard(ICON.time, `${Math.round(r.elapsed_ms)} мс`, "время"),
      statcard(ICON.tables, `${r.size}`, "байт"),
      statcard(ICON.api, r.source_type, "тип")));
    body.append(el("div", { class: "muted", style: "margin-top:8px;word-break:break-all" }, `IP: ${r.resolved_ip} · ${esc(r.final_url)}`));
    if (window.ForitKit) body.append(ForitKit.jsonTree(r));
    else body.append(el("pre", { class: "code" }, JSON.stringify(r, null, 2)));
    wrap.append(block);
  }

  // сводка источника
  if (d.summary) {
    const { block, body } = rblock(rbTitle("Что нашлось"), { accent: "#fb7132", note: d.summary.next_step || d.summary.note || "" });
    if (d.summary.counts) {
      body.append(el("div", { class: "chips" },
        ...Object.entries(d.summary.counts).map(([k, v]) => el("span", { class: "chip" }, `${k}: ${fmtNum(v)}`))));
    }
    if (d.summary.source_hints?.length) {
      body.append(el("div", { class: "rb-note" }, "Подсказки об источниках (полноценная рекомендация — в Extract, 1b):"));
      d.summary.source_hints.forEach((h) => body.append(finding("info", h.kind,
        h.location ? `${esc(h.location)}${h.confidence ? " · " + h.confidence : ""}` : `записей: ${h.records ?? "?"}${h.fields?.length ? " · поля: " + h.fields.join(", ") : ""}`)));
    }
    if (d.summary.shape) {
      body.append(el("div", { class: "chips" },
        el("span", { class: "chip" }, `форма: ${d.summary.shape}`),
        d.summary.items != null ? el("span", { class: "chip" }, `элементов: ${d.summary.items}`) : null));
      const keys = d.summary.item_keys || d.summary.top_level_keys;
      if (keys) body.append(el("div", { class: "muted", style: "margin-top:8px" }, "поля: " + keys.join(", ")));
    }
    wrap.append(block);
  }
  return wrap;
}


// =====================================================================
// WEB PARSER · Extract (1b): источник → поля → preview → export
// =====================================================================
const PA_SOURCES = ["text", "attr", "html", "url", "image", "file_url"];
const PA_TRANSFORMS = ["", "trim", "normalize_ws", "regex", "number", "date"];

async function runParserExtract() {
  const input = $("#paInput").value.trim();
  if (!input) { toast("Вставьте URL или HTML", "error"); return; }
  paState.input = input;
  await withState($("#paOut"), "Анализируем источники…", async () => {
    const d = await api("/api/parser/analyze", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input }),
    });
    if (d.error) return State.error(new ApiError(d.error, d.detail));
    paState.base_url = d.base_url || "";
    return renderExtract(d.recommendation);
  });
}

function renderExtract(rec) {
  const wrap = el("div", {});
  if (!rec || !rec.selected) {
    wrap.append(el("div", { class: "state" }, el("div", { class: "ico" }, "🕳️"), rec ? rec.reason : "Источников не найдено"));
    if (rec && rec.alternatives && rec.alternatives.length) wrap.append(renderAlternatives(rec));
    return wrap;
  }
  const sel = rec.selected;
  const { block, body } = rblock(rbTitle("Рекомендуемый источник"), { accent: "#22d3ee" });
  body.append(el("div", { class: "chips" },
    el("span", { class: "chip active" }, sel.kind),
    el("span", { class: "chip" }, `записей: ${sel.record_count == null ? "?" : sel.record_count}`),
    el("span", { class: "chip" }, `уверенность: ${rec.confidence}`),
    sel.stable_ids ? el("span", { class: "chip" }, "стабильные id") : null));
  body.append(el("div", { class: "muted", style: "margin:6px 0" }, `почему: ${rec.reason}`));
  (sel.evidence || []).forEach((e) => body.append(finding("info", "", e)));
  if (sel.location) body.append(el("div", { class: "mono", style: "margin-top:6px;word-break:break-all" }, esc(sel.location)));
  wrap.append(block);

  if (rec.alternatives && rec.alternatives.length) wrap.append(renderAlternatives(rec));

  if (sel.kind === "repeated_dom" && sel.schema) {
    paState.schema = JSON.parse(JSON.stringify(sel.schema));
    wrap.append(renderFieldEditor());
  } else if (sel.schema) {
    paState.schema = JSON.parse(JSON.stringify(sel.schema));
    const note = rblock(rbTitle("Поля"), { accent: "#a855f7", note: "Для JSON-источника берутся все ключи объектов. Настройка колонок — позже." });
    note.body.append(renderActions());
    wrap.append(note.block);
  }
  return wrap;
}

function renderAlternatives(rec) {
  const { block, body } = rblock(rbTitle("Другие источники"), { accent: "#fb7132", note: "Можно выбрать вопреки рекомендации." });
  rec.alternatives.forEach((a) => {
    const line = el("div", { class: "cand" },
      sevBadge(a.record_count != null ? "ok" : "info", a.kind),
      el("code", {}, esc(a.location || "")),
      el("span", { class: "muted" }, a.record_count != null ? `${a.record_count} зап.` : ((a.limitations && a.limitations[0]) || "не проверено")));
    if (a.schema) line.append(el("button", { class: "act", onclick: () => chooseSource(a) }, "Выбрать"));
    body.append(line);
  });
  return block;
}

function chooseSource(cand) {
  paState.schema = JSON.parse(JSON.stringify(cand.schema));
  toast(`Источник: ${cand.kind}`, "success");
  const holder = el("div", {});
  if (cand.kind === "repeated_dom") holder.append(renderFieldEditor());
  else { const n = rblock(rbTitle("Поля"), { accent: "#a855f7", note: "JSON-источник: берутся все ключи." }); n.body.append(renderActions()); holder.append(n.block); }
  $("#paOut").append(holder);
  holder.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderFieldEditor() {
  const { block, body } = rblock(rbTitle("Поля для сбора"), {
    accent: "#a855f7",
    note: "Правь имя, селектор (CSS или XPath), тип и трансформ. «Выбрать на странице» подставит CSS-селектор.",
    actions: [el("button", { class: "act", onclick: addField }, "+ поле"),
              el("button", { class: "act plain", onclick: visualSelect }, "🎯 Выбрать на странице")],
  });
  body.append(el("div", { class: "field", style: "margin-bottom:10px" },
    el("label", {}, "Контейнер (CSS-селектор карточки)"),
    el("input", { type: "text", id: "paContainer", value: paState.schema.container_selector || "" })));
  const table = el("table", { class: "dtable", id: "paFields" });
  table.append(el("thead", {}, el("tr", {}, ...["поле", "селектор", "тип", "источник", "трансформ", ""].map((h) => el("th", {}, h)))));
  const tb = el("tbody", {});
  (paState.schema.fields || []).forEach((f, i) => tb.append(fieldRow(f, i)));
  table.append(tb);
  body.append(el("div", { class: "dtable-wrap" }, table));
  body.append(renderActions());
  body.append(renderCollectBar());
  return block;
}

function fieldRow(f, i) {
  const selType = el("select", {}, ...["css", "xpath"].map((t) => el("option", { value: t, ...(t === f.selector_type ? { selected: "" } : {}) }, t)));
  const source = el("select", {}, ...PA_SOURCES.map((s) => el("option", { value: s, ...(s === f.source ? { selected: "" } : {}) }, s)));
  const transform = el("select", {}, ...PA_TRANSFORMS.map((t) => el("option", { value: t, ...(t === (f.transform || "") ? { selected: "" } : {}) }, t || "—")));
  return el("tr", { "data-i": i },
    el("td", {}, el("input", { type: "text", class: "pa-f-name", value: f.name || "" })),
    el("td", {}, el("input", { type: "text", class: "pa-f-sel", value: f.selector || "", placeholder: "h3 или .//span" })),
    el("td", {}, selType),
    el("td", {}, source),
    el("td", {}, transform),
    el("td", {}, el("button", { class: "act plain", onclick: (e) => { e.target.closest("tr").remove(); } }, "✕")));
}

function addField() {
  const tb = $("#paFields tbody");
  if (tb) tb.append(fieldRow({ name: "field" + (tb.children.length + 1), selector: "", selector_type: "css", source: "text" }, tb.children.length));
}

function renderActions() {
  return el("div", { class: "row", style: "margin-top:12px" },
    el("button", { class: "btn", onclick: runPreview }, "Проверить (preview)"),
    el("button", { class: "btn ghost", onclick: () => paExport("csv") }, "↓ CSV"),
    el("button", { class: "btn ghost", onclick: () => paExport("json") }, "↓ JSON"),
    el("button", { class: "btn ghost", onclick: () => paExport("jsonl") }, "↓ JSONL"),
    el("button", { class: "btn ghost", onclick: () => paExport("manifest") }, "↓ Manifest"),
    el("button", { class: "btn ghost", onclick: reproduceFromExtract }, "⟲ Reproduce"),
    el("button", { class: "btn ghost", onclick: () => handoffToChaos(paState.input) }, "→ Chaos"));
}

function collectSchema() {
  if (!paState.schema) return null;
  const schema = { source_kind: paState.schema.source_kind, container_type: "css", fields: [] };
  const container = $("#paContainer");
  schema.container_selector = container ? container.value.trim() : (paState.schema.container_selector || "");
  $$("#paFields tbody tr").forEach((tr) => {
    const name = $(".pa-f-name", tr).value.trim();
    if (!name) return;
    const selects = $$("select", tr);
    schema.fields.push({
      name,
      selector: $(".pa-f-sel", tr).value.trim(),
      selector_type: selects[0].value,
      source: selects[1].value,
      transform: selects[2].value || null,
    });
  });
  return schema;
}

async function runPreview() {
  const schema = collectSchema();
  if (!schema) { toast("Нет схемы", "error"); return; }
  paState.schema = schema;
  let holder = document.getElementById("paPreview");
  if (!holder) { holder = el("div", { id: "paPreview", style: "margin-top:16px" }); $("#paOut").append(holder); }
  await withState(holder, "Извлекаем…", async () => {
    const d = await api("/api/parser/preview", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ input: paState.input, schema, limit: 25 }),
    });
    if (d.error) return State.error(new ApiError(d.error, d.detail));
    return renderPreview(d);
  });
}

function renderPreview(d) {
  const wrap = el("div", {});
  wrap.append(el("div", { class: "chips" },
    el("span", { class: "chip active" }, `строк: ${d.rows.length}`),
    el("span", { class: "chip" }, `контейнеров: ${d.container_matches}`),
    d.assets && d.assets.length ? el("span", { class: "chip" }, `ассетов: ${d.assets.length}`) : null,
    d.truncated ? el("span", { class: "chip" }, "первые N") : null));
  (d.warnings || []).forEach((w) => wrap.append(finding("warn", "", w)));
  const cols = d.columns || [];
  const table = el("table", { class: "dtable" });
  table.append(el("thead", {}, el("tr", {}, ...cols.map((c) => el("th", {}, `${c} (${(d.match_counts && d.match_counts[c]) || 0})`)))));
  const tb = el("tbody", {});
  d.rows.slice(0, 25).forEach((r) => tb.append(el("tr", {}, ...cols.map((c) => el("td", { title: r[c] || "" }, esc(r[c] || ""))))));
  table.append(tb);
  wrap.append(el("div", { class: "dtable-wrap" }, table));
  return wrap;
}

async function paExport(fmt) {
  const schema = collectSchema();
  if (!schema) { toast("Нет схемы", "error"); return; }
  paState.schema = schema;
  toast("Готовим файл…");
  try {
    const res = await fetch("/api/parser/export?format=" + fmt, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ input: paState.input, schema, limit: 200 }),
    });
    if (!res.ok) { toast("Экспорт не удался", "error"); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = el("a", { href: url, download: fmt === "manifest" ? "assets-manifest.json" : "extract." + (fmt === "jsonl" ? "jsonl" : fmt) });
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    toast("Файл скачивается", "success");
  } catch (e) { toast(String(e), "error"); }
}

// Визуальный выбор: санитизированный HTML в sandbox-iframe.
// sandbox="allow-same-origin" БЕЗ allow-scripts: remote JS не исполняется, но
// родитель читает DOM iframe, чтобы по клику построить CSS-селектор.
let paLastField = null;
document.addEventListener("focusin", (e) => { if (e.target.classList && e.target.classList.contains("pa-f-sel")) paLastField = e.target; });

async function visualSelect() {
  if (!paState.input) { toast("Сначала анализ", "error"); return; }
  toast("Готовим страницу…");
  let d;
  try {
    d = await api("/api/parser/sandbox", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input: paState.input }) });
  } catch (e) { toast(String(e), "error"); return; }
  if (d.error) { toast(d.error, "error"); return; }
  const overlay = el("div", { class: "pa-visual" });
  // iframe opaque-origin: allow-scripts БЕЗ allow-same-origin. Исполняется только
  // наш picker (чужие скрипты вырезаны сервером). Родитель НЕ читает DOM iframe —
  // получает селектор строго через postMessage.
  const frame = el("iframe", { class: "pa-visual-frame", sandbox: "allow-scripts", srcdoc: d.html });
  const bar = el("div", { class: "pa-visual-bar" },
    el("span", {}, "Кликни по нужному элементу — подставим CSS-селектор"),
    el("button", { class: "btn sm ghost", onclick: cleanup }, "Закрыть"));
  overlay.append(bar, frame);
  document.body.append(overlay);

  function onMessage(ev) {
    if (ev.source !== frame.contentWindow) return;           // только это окно
    const data = ev.data;
    if (!data || data.type !== "forit-picker-select") return; // только наш тип
    if (typeof data.selector !== "string") return;            // только строку
    const selector = data.selector.slice(0, 300);             // ограничиваем длину
    if (paLastField) { paLastField.value = selector; toast("Селектор: " + selector, "success"); }
    else toast("Селектор: " + selector + " (сначала выберите поле)");
    cleanup();
  }
  function cleanup() {
    window.removeEventListener("message", onMessage);
    overlay.remove();
  }
  window.addEventListener("message", onMessage);
}


// =====================================================================
// WEB PARSER · Multi-page collection (1d): каталог из N страниц → dataset
// =====================================================================
let paCollect = null; // {job_id, cursor, cancelled}

// добавляем кнопку сбора в набор действий Extract (только для URL-источника)
function renderCollectBar() {
  const isUrl = /^https?:\/\/\S+$/i.test((paState.input || "").trim());
  const box = el("div", { class: "row", style: "margin-top:10px" });
  const btn = el("button", { class: "btn", onclick: startCollect }, "🕷 Собрать все страницы");
  if (!isUrl) {
    btn.disabled = true;
    btn.title = "Многостраничный сбор доступен только для URL-источника";
  }
  box.append(btn, el("span", { class: "muted", style: "align-self:center" },
    isUrl ? "Обойдёт пагинацию и соберёт все страницы в один датасет" : "Вставьте URL каталога, чтобы собрать несколько страниц"));
  return box;
}

async function startCollect() {
  const schema = collectSchema();
  if (!schema) { toast("Нет схемы", "error"); return; }
  paState.schema = schema;
  let holder = document.getElementById("paCollectOut");
  if (!holder) { holder = el("div", { id: "paCollectOut", style: "margin-top:16px" }); $("#paOut").append(holder); }
  holder.replaceChildren(State.loading("Запускаем сбор…"));
  let start;
  try {
    start = await api("/api/parser/collect", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ input: paState.input, schema, pagination: "auto" }),
    });
  } catch (e) { render(holder, State.error(e)); return; }
  if (start.error) { render(holder, State.error(new ApiError(start.error))); return; }
  paCollect = { job_id: start.id, cursor: start.cursor, cancelled: false };
  await pumpCollect(holder);
}

function collectUI(holder) {
  const bar = ForitKit ? ForitKit.progressBar() : null;
  const stat = el("div", { class: "chips", style: "margin:10px 0" });
  const cancel = el("button", { class: "btn ghost sm", onclick: cancelCollect }, "Отменить");
  const body = el("div", {});
  const { block } = rblock(rbTitle("Сбор каталога"), { accent: "#22d3ee", actions: [cancel] });
  const inner = block.querySelector(".rb-body");
  if (bar) inner.append(bar);
  inner.append(stat, body);
  holder.replaceChildren(block);
  return { bar, stat, body };
}

async function cancelCollect() {
  if (!paCollect) return;
  paCollect.cancelled = true;
  try { await api(`/api/parser/collect/${paCollect.job_id}/cancel`, { method: "POST" }); } catch {}
  toast("Останавливаем…");
}

async function pumpCollect(holder) {
  const ui = collectUI(holder);
  const job = paCollect;
  while (true) {
    if (!job || paCollect !== job) return;  // сменили режим/запустили другое — тихо выходим
    let st;
    try {
      st = await api(`/api/parser/collect/${job.job_id}/step`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ cursor: job.cursor }),
      });
    } catch (e) { render(holder, State.error(e)); return; }
    job.cursor = st.cursor;
    updateCollectUI(ui, st);
    if (["completed", "failed", "cancelled"].includes(st.status)) { finishCollect(holder, ui, st); return; }
    await new Promise((r) => setTimeout(r, 120));
  }
}

function updateCollectUI(ui, st) {
  const p = st.partial || {};
  if (ui.bar) { ui.bar.setProgress(st.progress || 0); ui.bar.setLabel(`${p.pages || 0} стр · ${p.rows || 0} строк`); }
  ui.stat.replaceChildren(...[
    el("span", { class: "chip active" }, `статус: ${st.status}`),
    el("span", { class: "chip" }, `страниц: ${p.pages || 0}`),
    el("span", { class: "chip" }, `строк: ${p.rows || 0}`),
    p.queued ? el("span", { class: "chip" }, `в очереди: ${p.queued}`) : null,
  ].filter(Boolean));
}

function finishCollect(holder, ui, st) {
  const p = st.partial || {};
  const body = ui.body;
  body.replaceChildren();
  if ((st.status === "failed" || st.status === "cancelled") && (p.rows || 0) === 0) {
    body.append(jobFailedNotice(st, 0, "Сбор"));
    return;
  }
  if (p.stopped_reason) body.append(finding(p.partial ? "warn" : "info", "", `Остановка: ${p.stopped_reason}`));
  (st.errors || []).slice(0, 5).forEach((e) => body.append(finding("warn", "", e)));

  // schema drift между страницами
  if (p.schema_drift && p.schema_drift.length) {
    body.append(el("div", { class: "rb-note", style: "margin-top:6px" }, "Дрейф схемы между страницами:"));
    p.schema_drift.forEach((d) => body.append(finding(
      d.mixed_types ? "warn" : "ok", d.field,
      `заполнено ${d.present_pct}% · тип: ${d.dominant_type}${d.mixed_types ? " (смешанные!)" : ""}`)));
  }

  // экспорт собранного датасета
  if (st.status === "completed" || (p.rows || 0) > 0) {
    const jid = paCollect.job_id;
    body.append(el("div", { class: "row", style: "margin-top:12px" },
      el("a", { class: "btn", href: `/api/parser/collect/${jid}/export?format=csv`, target: "_blank" }, `↓ CSV (${p.rows || 0})`),
      el("a", { class: "btn ghost", href: `/api/parser/collect/${jid}/export?format=json`, target: "_blank" }, "↓ JSON"),
      el("a", { class: "btn ghost", href: `/api/parser/collect/${jid}/export?format=jsonl`, target: "_blank" }, "↓ JSONL"),
      el("a", { class: "btn ghost", href: `/api/parser/collect/${jid}/export?format=manifest`, target: "_blank" }, "↓ Manifest")));
  }
  if (st.status === "completed") toast(`Собрано ${p.rows || 0} строк с ${p.pages || 0} страниц`, "success");
}


// =====================================================================
// WEB PARSER · Explore / Request Builder (1c): URL/curl → RequestSpec → выполнить
// =====================================================================
const PA_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"];

async function runParserExplore() {
  const input = $("#paInput").value.trim();
  const out = $("#paOut");
  if (!input) { toast("Вставьте URL или строку curl", "error"); return; }
  paState.input = input;
  await withState(out, "Разбираем запрос…", async () => {
    const d = await api("/api/parser/build-request", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input }),
    });
    if (d.error) return State.error(new ApiError(d.error));
    return renderRequestBuilder(d.request);
  });
}

function renderRequestBuilder(spec) {
  const wrap = el("div", {});
  const method = el("select", { id: "paReqMethod" }, ...PA_METHODS.map((m) => el("option", { value: m, ...(m === spec.method ? { selected: "" } : {}) }, m)));
  const url = el("input", { type: "text", id: "paReqUrl", value: spec.url || "" });
  const headersText = Object.entries(spec.headers || {}).map(([k, v]) => `${k}: ${v}`).join("\n");
  const headers = el("textarea", { id: "paReqHeaders", placeholder: "Header: value (по строке)", style: "min-height:70px" }, headersText);
  const body = el("textarea", { id: "paReqBody", placeholder: "тело запроса (для POST/PUT)", style: "min-height:70px" }, spec.body || "");

  const { block, body: bd } = rblock(rbTitle("Запрос"), { accent: "#a855f7", note: "Явный запрос как в Postman: robots не применяется, SSRF-защита остаётся. Секреты не сохраняются на сервере." });
  bd.append(
    el("div", { class: "row" },
      el("div", { class: "field", style: "flex:0 0 130px" }, el("label", {}, "Метод"), method),
      el("div", { class: "field", style: "flex:1" }, el("label", {}, "URL"), url)),
    el("div", { class: "field" }, el("label", {}, "Заголовки"), headers),
    el("div", { class: "field" }, el("label", {}, "Тело"), body),
    el("div", { class: "row" },
      el("button", { class: "btn", onclick: executeRequest }, "Выполнить →"),
      el("button", { class: "btn ghost", onclick: () => { $("#paReqBody").value = ""; $("#paReqHeaders").value = ""; } }, "Очистить заголовки/тело")));
  wrap.append(block);
  wrap.append(el("div", { id: "paReqOut", style: "margin-top:14px" }));
  return wrap;
}

function collectRequest() {
  const headers = {};
  ($("#paReqHeaders").value || "").split("\n").forEach((line) => {
    const i = line.indexOf(":");
    if (i > 0) headers[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  });
  return {
    method: $("#paReqMethod").value,
    url: $("#paReqUrl").value.trim(),
    headers,
    body: $("#paReqBody").value || null,
  };
}

async function executeRequest() {
  const req = collectRequest();
  if (!req.url) { toast("Укажите URL", "error"); return; }
  paState.lastRequest = req;
  await withState($("#paReqOut"), "Выполняем запрос…", async () => {
    const d = await api("/api/parser/request", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(req),
    });
    if (d.error) return State.error(new ApiError(d.error, d.detail));
    return renderRequestResponse(d);
  });
}

function renderRequestResponse(d) {
  const wrap = el("div", {});
  const r = d.response;
  const { block, body } = rblock(rbTitle(`Ответ · ${r.status}`), { accent: "#22d3ee" });
  body.append(el("div", { class: "statgrid" },
    statcard(ICON.status, `${r.status}`, "HTTP", r.status < 400 ? "ok" : "alert"),
    statcard(ICON.time, `${Math.round(r.elapsed_ms)} мс`, "время"),
    statcard(ICON.tables, `${r.size}`, "байт"),
    statcard(ICON.api, r.source_type, "тип")));
  body.append(el("div", { class: "muted", style: "margin-top:6px;word-break:break-all" }, `IP: ${r.resolved_ip} · ${esc(r.final_url)}`));
  if (r.redirect_chain?.length) body.append(el("div", { class: "rb-note" }, `редиректов: ${r.redirect_chain.length}`));

  // прогрессивное раскрытие: заголовки / тело / структура
  const tabs = [];
  if (window.ForitKit) {
    tabs.push({ id: "headers", label: "Заголовки", render: () => ForitKit.jsonTree(r.headers) });
    if (d.json !== undefined && d.json !== null) tabs.push({ id: "structure", label: "Структура", render: () => ForitKit.jsonTree(d.json) });
    tabs.push({ id: "raw", label: "Тело (raw)", render: () => el("pre", { class: "code" }, r.body_preview || "(пусто)") });
    body.append(ForitKit.tabs(tabs));
  } else {
    body.append(el("pre", { class: "code" }, r.body_preview || ""));
  }

  // передать в Extract (для GET — по URL; для остального пока подсказка)
  const toExtract = el("button", { class: "btn ghost", onclick: () => handoffToExtract(r) }, "→ извлечь данные (Extract)");
  if ((paState.lastRequest?.method || "GET") !== "GET") {
    toExtract.disabled = true;
    toExtract.title = "Передача не-GET запроса в Extract — в следующей итерации";
  }
  const reproEx = el("button", { class: "btn ghost", onclick: () => showReproduce(paState.lastRequest, null) }, "⟲ Reproduce");
  const chaosEx = el("button", { class: "btn ghost", onclick: () => handoffToChaos(r.final_url) }, "→ Chaos");
  body.append(el("div", { class: "row", style: "margin-top:12px" }, toExtract, reproEx, chaosEx));
  wrap.append(block);
  return wrap;
}

function handoffToExtract(r) {
  $("#paInput").value = r.final_url;
  selectParserMode("extract");
  runParserExtract();
}


// =====================================================================
// WEB PARSER · Reproduce (1f) + handoff в Chaos
// =====================================================================
function paCodeBox(title, code) {
  const pre = el("pre", { class: "code" }, code);
  const copy = el("button", { class: "btn sm ghost", onclick: async () => {
    try { await navigator.clipboard.writeText(code); toast("Скопировано", "success"); }
    catch { const r = document.createRange(); r.selectNode(pre); getSelection().removeAllRanges(); getSelection().addRange(r); document.execCommand("copy"); toast("Скопировано", "success"); }
  } }, "Копировать");
  return el("div", { style: "margin-bottom:12px" },
    el("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:4px" },
      el("b", {}, title), copy), pre);
}

async function showReproduce(request, schema) {
  let d;
  try {
    d = await api("/api/parser/reproduce", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ request, schema: schema || null }),
    });
  } catch (e) { toast(String(e), "error"); return; }
  if (d.error) { toast(d.error, "error"); return; }
  const content = el("div", {},
    paCodeBox("curl", d.curl),
    paCodeBox("Python (requests + lxml)", d.python),
    el("div", { class: "muted" }, "Секреты заменены плейсхолдерами из окружения ($AUTH_TOKEN, $API_KEY…)."));
  if (window.ForitKit) { const m = ForitKit.dialog({ title: "Воспроизвести", content }); m.open(); }
  else { $("#paOut").append(content); }
}

function reproduceFromExtract() {
  const schema = collectSchema();
  showReproduce({ method: "GET", url: paState.input, headers: {} }, schema);
}

function handoffToChaos(url) {
  try { sessionStorage.setItem("forit-chaos-target", url || paState.input || ""); } catch {}
  navigate("chaos");
}

// баннер в Chaos, если пришли из Web Parser (Chaos-проверка сайта — отдельная фаза)
function showChaosHandoff() {
  let url = null;
  try { url = sessionStorage.getItem("forit-chaos-target"); sessionStorage.removeItem("forit-chaos-target"); } catch {}
  if (!url) return;
  const inp = $("#csUrl"); if (inp) { inp.value = url; runSecurityCheck(); return; }
  const out = $("#chOut");
  if (!out) return;
  const note = el("div", { class: "rblock", style: "--tacc:#f43f5e" });
  note.innerHTML =
    `<div class="rb-head"><div class="rb-title"><span class="dotmark"></span>Из Web Parser</div></div>` +
    `<div class="rb-body"><p class="rb-note" style="margin:0">Получен URL для проверки безопасности: ` +
    `<span class="mono" style="word-break:break-all">${esc(url)}</span>. ` +
    `Полноценная проверка сайта (Chaos Security Check) появится в отдельной фазе — сейчас доступен генератор плохих ответов ниже.</p></div>`;
  out.replaceChildren(note);
}


// =====================================================================
// WEB PARSER · Crawl / Audit (1e): обход сайта → технические факты
// =====================================================================
let paCrawl = null;

async function runCrawl(mode) {
  const input = $("#paInput").value.trim();
  const out = $("#paOut");
  if (!input) { toast("Вставьте URL", "error"); return; }
  if (!/^https?:\/\/\S+$/i.test(input)) { toast("Обход требует URL", "error"); return; }
  paState.input = input;
  out.replaceChildren(State.loading("Запускаем обход…"));
  let start;
  try {
    start = await api("/api/parser/crawl", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input }) });
  } catch (e) { render(out, State.error(e)); return; }
  if (start.error) { render(out, State.error(new ApiError(start.error))); return; }
  paCrawl = { job_id: start.id, cursor: start.cursor, mode, cancelled: false };
  await pumpCrawl(out);
}

function crawlUI(out) {
  const bar = window.ForitKit ? ForitKit.progressBar() : null;
  const stat = el("div", { class: "chips", style: "margin:10px 0" });
  const cancel = el("button", { class: "btn ghost sm", onclick: cancelCrawl }, "Отменить");
  const { block } = rblock(rbTitle(paCrawl.mode === "audit" ? "Аудит сайта" : "Обход сайта"), { accent: "#22d3ee", actions: [cancel] });
  const inner = block.querySelector(".rb-body");
  if (bar) inner.append(bar);
  inner.append(stat);
  out.replaceChildren(block);
  return { bar, stat, inner };
}

async function cancelCrawl() {
  if (!paCrawl) return;
  paCrawl.cancelled = true;
  try { await api(`/api/parser/crawl/${paCrawl.job_id}/cancel`, { method: "POST" }); } catch {}
  toast("Останавливаем…");
}

async function pumpCrawl(out) {
  const ui = crawlUI(out);
  const job = paCrawl;
  while (true) {
    if (!job || paCrawl !== job) return;  // сменили режим/запустили другое — тихо выходим
    let st;
    try {
      st = await api(`/api/parser/crawl/${job.job_id}/step`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ cursor: job.cursor }),
      });
    } catch (e) { render(out, State.error(e)); return; }
    job.cursor = st.cursor;
    const p = st.partial || {};
    if (ui.bar) { ui.bar.setProgress(st.progress || 0); ui.bar.setLabel(`${p.pages || 0} стр · ${p.broken || 0} broken`); }
    ui.stat.replaceChildren(...[
      el("span", { class: "chip active" }, `статус: ${st.status}`),
      el("span", { class: "chip" }, p.max_pages ? `страниц: ${p.pages || 0} / ${p.max_pages}` : `страниц: ${p.pages || 0}`),
      el("span", { class: "chip" }, `broken: ${p.broken || 0}`),
      el("span", { class: "chip" }, `redirects: ${p.redirects || 0}`),
      p.queued ? el("span", { class: "chip" }, `найдено ссылок: ${p.queued}`) : null,
    ].filter(Boolean));
    if (["completed", "failed", "cancelled"].includes(st.status)) { await finishCrawl(ui.inner, st); return; }
    await new Promise((r) => setTimeout(r, 120));
  }
}

// Единый честный вывод для провалившейся / пустой задачи (crawl, audit).
// Никакого зелёного «всё хорошо», никаких null/undefined, экспорт пустого нуля не предлагаем.
function jobFailedNotice(st, count, label) {
  const box = el("div", {});
  const failed = st.status === "failed" || st.status === "cancelled";
  const title = st.status === "cancelled" ? `${label} отменён` : failed ? `${label} не выполнен` : `${label}: нет данных`;
  const reasons = (st.errors || []).filter(Boolean);
  let reason = reasons[0] || (st.partial && st.partial.stopped_reason) || "";
  reason = reason.replace(/^https?:\/\/\S+?:\s*/i, "").replace(/^\w+Error:\s*/, "").trim();
  // человекочитаемая причина для частых случаев
  if (/RobotsDisallowed|robots\.txt/i.test(reason)) reason = "robots.txt сайта запрещает обход этих страниц.";
  else if (/UnsafeUrl|SSRF|приватн/i.test(reason)) reason = "адрес отклонён защитой (SSRF / приватная сеть / нестандартный порт).";
  else if (/разрезолвить|getaddrinfo|DNS/i.test(reason)) reason = "не удалось определить адрес сайта (DNS): проверьте имя хоста.";
  box.append(finding("alert", "", reason
    ? `${title}: ${reason}`
    : `${title}. Проверено страниц: ${count}. Результата для показа нет.`));
  return box;
}

async function finishCrawl(inner, st) {
  const p = st.partial || {};
  const pages = p.pages || 0;
  const label = paCrawl && paCrawl.mode === "audit" ? "Аудит" : "Обход";
  // Отмена — законный финал: показываем, сколько успели, без зелёного «всё ок».
  if (st.status === "cancelled") {
    inner.append(finding("info", "", `${label} остановлен. Успели обойти страниц: ${pages}.`));
    return;
  }
  if (st.status === "failed" || pages === 0) {
    inner.append(jobFailedNotice(st, pages, label));
    return;
  }

  let rows = p.sample || [];
  try { rows = await api(`/api/parser/crawl/${paCrawl.job_id}/export?format=json`); } catch {}

  if (p.stopped_reason) inner.append(finding(p.partial ? "warn" : "info", "", `Итог: ${p.stopped_reason}`));
  inner.append(el("div", { class: "chips", style: "margin:6px 0" },
    ...Object.entries(p.statuses || {}).map(([s, n]) => el("span", { class: `chip ${s >= "400" ? "" : "active"}` }, `${s}: ${n}`))));

  // проблемы (для Audit — на первом плане)
  const broken = rows.filter((r) => r.broken || r.error);
  const noTitle = rows.filter((r) => !r.broken && !r.error && (r.content_type || "").includes("html") && !r.title);
  if (broken.length || noTitle.length) {
    const iss = rblock(rbTitle("Проблемы", broken.length + noTitle.length), { accent: "#f43f5e" });
    broken.forEach((r) => iss.body.append(finding("alert", String(r.status || "—"), `${r.error || "недоступна"} · ${r.url}${r.source ? " ← " + r.source : ""}`)));
    noTitle.forEach((r) => iss.body.append(finding("warn", "no title", r.url)));
    inner.append(iss.block);
  } else {
    inner.append(finding("ok", "", `Проверено страниц: ${pages}. Битых ссылок и пустых title не найдено.`));
  }

  // таблица страниц
  const cols = ["status", "url", "title", "depth", "redirected"];
  const table = el("table", { class: "dtable" });
  table.append(el("thead", {}, el("tr", {}, ...cols.map((c) => el("th", {}, c)))));
  const tb = el("tbody", {});
  rows.slice(0, 200).forEach((r) => tb.append(el("tr", {},
    el("td", { class: r.broken ? "" : "num", style: r.broken ? "color:var(--alert)" : "" }, String(r.status ?? "—")),
    el("td", { title: r.url, style: "max-width:340px;overflow:hidden;text-overflow:ellipsis" }, esc(r.url)),
    el("td", {}, esc(r.title || "")),
    el("td", { class: "num" }, String(r.depth)),
    el("td", {}, r.redirected ? "→ " + esc(r.final_url || "") : ""))));
  table.append(tb);
  inner.append(el("div", { class: "dtable-wrap" }, table));

  // экспорт
  const jid = paCrawl.job_id;
  inner.append(el("div", { class: "row", style: "margin-top:12px" },
    el("a", { class: "btn", href: `/api/parser/crawl/${jid}/export?format=csv`, target: "_blank" }, `↓ CSV (${rows.length})`),
    el("a", { class: "btn ghost", href: `/api/parser/crawl/${jid}/export?format=json`, target: "_blank" }, "↓ JSON")));
  if (st.status === "completed") toast(`Обойдено ${p.pages || 0} страниц`, "success");
}


// =====================================================================
// CHAOS · Passive Security Check (1a)
// =====================================================================
let chaosReady = false;
const CS_SEV = { high: ["alert", "✕"], medium: ["warn", "⚠"], low: ["info", "·"], info: ["info", "·"] };
function initChaosOnce() {
  if (chaosReady) return;
  chaosReady = true;
  const go = $("#csGo");
  if (go) go.addEventListener("click", runSecurityCheck);
  const site = $("#csSite");
  if (site) site.addEventListener("click", runSiteAudit);
  const inp = $("#csUrl");
  if (inp) inp.addEventListener("keydown", (e) => { if (e.key === "Enter") runSecurityCheck(); });
}
async function runSecurityCheck() {
  const url = $("#csUrl").value.trim();
  if (!url) { toast("Вставьте URL сайта", "error"); return; }
  await withState($("#csOut"), "Проверяем сайт…", async () => {
    const d = await api("/api/chaos/v2/check", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url }),
    });
    if (d.error) return State.error(new ApiError(d.error, d.detail));
    return renderSecurityReport(d);
  });
}
function renderSecurityReport(d) {
  const wrap = el("div", {});
  const s = d.summary || {};
  const worst = s.high ? "alert" : s.medium ? "warn" : (s.low || s.info) ? "info" : "ok";
  wrap.append(el("div", { class: `verdict ${worst}` },
    el("span", { class: "big" }, d.https ? "🔒" : "⚠"),
    el("span", {}, `${d.https ? "HTTPS" : "Без HTTPS"} · ${prettyUrl(d.final_url)}`)));

  wrap.append(el("div", { class: "chips", style: "margin-bottom:14px" },
    el("span", { class: `chip ${s.high ? "active" : ""}` }, `HIGH: ${s.high || 0}`),
    el("span", { class: "chip" }, `MEDIUM: ${s.medium || 0}`),
    el("span", { class: "chip" }, `LOW: ${s.low || 0}`),
    el("span", { class: "chip" }, `INFO: ${s.info || 0}`)));

  const all = [...(d.findings || []), ...(d.origin_findings || [])];
  if (!all.length) {
    wrap.append(el("div", { class: "state" }, el("div", { class: "ico" }, "✓"), "Очевидных пассивных проблем не найдено."));
    return wrap;
  }
  all.forEach((f) => {
    const [cls, mark] = CS_SEV[f.severity] || ["info", "·"];
    const card = el("div", { class: "ent", style: "margin-bottom:10px" });
    card.append(el("div", { class: "ent-top" },
      el("div", { class: "ent-meta" }, sevBadge(cls, f.severity.toUpperCase()), el("strong", {}, f.title)),
      el("span", { class: "muted mono" }, f.category)));
    // el() вставляет строки как textContent (createTextNode) — это уже безопасно.
    // Дополнительный esc() здесь давал двойное экранирование: <iframe> → &lt;iframe&gt;.
    card.append(el("dl", { class: "kv kv-wide" },
      el("dt", { class: "muted" }, "Обнаружено"), el("dd", {}, f.evidence),
      el("dt", { class: "muted" }, "Почему важно"), el("dd", {}, f.why),
      el("dt", { class: "muted" }, "Как исправить"), el("dd", {}, f.recommendation)));
    wrap.append(card);
  });
  return wrap;
}


// =====================================================================
// CHAOS · Site-wide Passive Audit (1b)
// =====================================================================
let csAudit = null;
async function runSiteAudit() {
  const url = $("#csUrl").value.trim();
  if (!url) { toast("Вставьте URL сайта", "error"); return; }
  const out = $("#csOut");
  out.replaceChildren(State.loading("Запускаем проверку сайта…"));
  let start;
  try {
    start = await api("/api/chaos/v2/audit", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url }) });
  } catch (e) { render(out, State.error(e)); return; }
  if (start.error) { render(out, State.error(new ApiError(start.error))); return; }
  csAudit = { job_id: start.id, cursor: start.cursor };
  await pumpAudit(out);
}
async function pumpAudit(out) {
  const bar = window.ForitKit ? ForitKit.progressBar() : null;
  const stat = el("div", { class: "chips", style: "margin:10px 0" });
  const cancel = el("button", { class: "btn ghost sm", onclick: async () => { try { await api(`/api/chaos/v2/audit/${csAudit.job_id}/cancel`, { method: "POST" }); } catch {} toast("Останавливаем…"); } }, "Отменить");
  const { block } = rblock(rbTitle("Проверка сайта"), { accent: "#f43f5e", actions: [cancel] });
  const inner = block.querySelector(".rb-body");
  if (bar) inner.append(bar);
  inner.append(stat);
  out.replaceChildren(block);
  const job = csAudit;
  while (true) {
    let st;
    try {
      st = await api(`/api/chaos/v2/audit/${job.job_id}/step`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ cursor: job.cursor }) });
    } catch (e) { render(out, State.error(e)); return; }
    job.cursor = st.cursor;
    const p = st.partial || {};
    if (bar) { bar.setProgress(st.progress || 0); bar.setLabel(`${p.pages_checked || 0} проверено`); }
    stat.replaceChildren(...[
      el("span", { class: "chip active" }, `статус: ${st.status}`),
      el("span", { class: "chip" }, `страниц: ${p.pages_checked || 0}`),
      p.pages_failed ? el("span", { class: "chip" }, `ошибок: ${p.pages_failed}`) : null,
      p.queued ? el("span", { class: "chip" }, `в очереди: ${p.queued}`) : null,
    ].filter(Boolean));
    if (["completed", "failed", "cancelled"].includes(st.status)) { finishAudit(inner, st); return; }
    await new Promise((r) => setTimeout(r, 130));
  }
}
function finishAudit(inner, st) {
  const p = st.partial || {};
  const s = p.summary || {};
  const checked = p.pages_checked || 0;
  // Провал или ноль проверенных страниц: честный отказ, без зелёных итогов и пустого экспорта
  if (st.status === "failed" || st.status === "cancelled" || checked === 0) {
    inner.append(jobFailedNotice(st, checked, "Проверка сайта"));
    return;
  }
  if (p.stopped_reason) inner.append(finding(p.partial ? "warn" : "info", "", `Итог: ${p.stopped_reason}`));
  inner.append(el("div", { class: "chips", style: "margin:8px 0" },
    el("span", { class: "muted" }, `${p.pages_checked || 0} страниц проверено · `),
    el("span", { class: `chip ${s.high ? "active" : ""}` }, `HIGH: ${s.high || 0}`),
    el("span", { class: "chip" }, `MEDIUM: ${s.medium || 0}`),
    el("span", { class: "chip" }, `LOW: ${s.low || 0}`),
    el("span", { class: "chip" }, `INFO: ${s.info || 0}`)));

  const CS_SEV = { high: ["alert", "✕"], medium: ["warn", "⚠"], low: ["info", "·"], info: ["info", "·"] };
  // origin-level findings (TLS / security.txt / robots / methods) — один раз на сайт
  if (p.origin_findings && p.origin_findings.length) {
    inner.append(el("div", { class: "rb-note", style: "margin-top:6px" }, "Origin-уровень (один раз на сайт):"));
    p.origin_findings.forEach((f) => {
      const [cls] = CS_SEV[f.severity] || ["info"];
      inner.append(finding(cls === "alert" ? "alert" : cls === "warn" ? "warn" : "info", f.category || "", `${f.title} — ${f.evidence || ""}`));
    });
  }
  if (p.aggregated_findings && p.aggregated_findings.length) inner.append(el("div", { class: "rb-note", style: "margin-top:6px" }, "По страницам:"));
  (p.aggregated_findings || []).forEach((a) => {
    const [cls] = CS_SEV[a.severity] || ["info"];
    const det = el("details", { class: "ent", style: "margin-bottom:8px" });
    det.append(el("summary", {},
      sevBadge(cls, a.severity.toUpperCase()), " ", el("strong", {}, a.title),
      el("span", { class: "muted", style: "margin-left:8px" }, `${a.affected_pages} / ${a.checked_pages} страниц`)));
    const body = el("div", { style: "padding:8px 0 0 4px" });
    (a.examples || []).forEach((u) => body.append(el("div", { class: "mono", style: "font-size:.82rem;word-break:break-all" }, esc(u))));
    if (a.affected_pages > a.examples.length) body.append(el("div", { class: "muted" }, `…и ещё ${a.affected_pages - a.examples.length}`));
    det.append(body);
    inner.append(det);
  });

  const jid = csAudit.job_id;
  inner.append(el("div", { class: "row", style: "margin-top:12px" },
    el("a", { class: "btn ghost", href: `/api/chaos/v2/audit/${jid}/export?format=csv`, target: "_blank" }, "↓ CSV (по страницам)"),
    el("a", { class: "btn ghost", href: `/api/chaos/v2/audit/${jid}/export?format=json`, target: "_blank" }, "↓ JSON")));
  if (st.status === "completed") toast(`Проверено ${p.pages_checked || 0} страниц`, "success");
}


// =====================================================================
// FILE INSPECTOR · что файл знает о тебе (/api/file)
// =====================================================================
let fiReady = false;
let fiFile = null;
const FI_CAT = { location: "📍 геолокация", device: "устройство", software: "софт", author: "автор", timestamps: "даты", document: "документ", other: "прочее" };
function initFileInspectorOnce() {
  if (fiReady) return;
  fiReady = true;
  const inp = $("#fiFile");
  if (inp) inp.addEventListener("change", (e) => { fiFile = e.target.files[0]; if (fiFile) runFileInspect(); });
  const drop = $("#fiDrop");
  if (drop) {
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("drag"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("drag"));
    drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("drag"); fiFile = e.dataTransfer.files[0]; if (fiFile) runFileInspect(); });
  }
}
async function runFileInspect() {
  const fd = new FormData(); fd.append("file", fiFile);
  await withState($("#fiOut"), "Читаем файл…", async () => {
    const res = await fetch("/api/file/inspect", { method: "POST", body: fd });
    if (!res.ok) { const j = await res.json().catch(() => null); throw new ApiError(j?.error?.message || "Ошибка", j?.error?.detail); }
    return renderFileReport(await res.json());
  });
}
function fiStat(v, l) {
  const long = String(v).length > 22;
  return el("div", { class: "statcard" }, el("div", {}, el("div", { class: `sc-v${long ? " long" : ""}`, title: String(v) }, v), el("div", { class: "sc-l" }, l)));
}
// Значение метаданных: короткое — как есть; крупное (XML/JSON/blob) — сворачиваем
// в подпись типа с кнопками «показать полностью» и «копировать», не вываливая простыню.
function fiMetaValue(m) {
  const val = String(m.value == null ? "" : m.value);
  if (!m.large) return el("span", { style: "word-break:break-word" }, esc(val) || el("span", { class: "muted" }, "(пусто)"));
  const det = el("details", { class: "fi-val" });
  const len = (m.value_length || val.length).toLocaleString("ru-RU");
  det.append(el("summary", {}, `${m.type_label || "данные"} · ${len} символов — показать`));
  det.append(el("pre", { class: "fi-raw" }, val.slice(0, 4000) + (val.length > 4000 ? "\n…(обрезано для показа, копируется целиком)" : "")));
  det.append(el("button", { class: "btn ghost sm", onclick: () => copyText(val) }, "Копировать значение"));
  return det;
}
function copyText(t) {
  navigator.clipboard.writeText(t).then(() => toast("Скопировано", "success"))
    .catch(() => toast("Не удалось скопировать", "error"));
}
function fiSensLine(m) {
  const shown = m.large ? (m.type_label || "данные") : String(m.value);
  return finding("alert", FI_CAT[m.category] || m.category, `${m.label || m.key}: ${esc(shown)}`);
}
function renderFileReport(d) {
  const wrap = el("div", {});
  const { block, body } = rblock(rbTitle(esc(d.name)), { accent: "#c084fc" });
  body.append(el("div", { class: "statgrid" },
    fiStat(d.format, "формат"),
    fiStat(d.mime, "MIME"),
    fiStat(fmtBytes(d.size_bytes), "размер"),
    (d.width && d.height) ? fiStat(`${d.width}×${d.height}`, "px") : null,
    fiStat(d.metadata.length, "метаданных")));
  body.append(el("div", { class: "mono", style: "margin-top:8px;word-break:break-all;font-size:.8rem" }, "sha256: " + d.sha256));
  wrap.append(block);

  const sens = d.sensitive_metadata || [];
  if (sens.length) {
    const iss = rblock(rbTitle("Приватные данные", sens.length), { accent: "#f43f5e" });
    iss.body.append(el("div", { class: "rb-note", style: "margin-top:0" }, "Эти поля могут деанонимизировать автора/устройство/место — их стоит убрать перед публикацией."));
    sens.forEach((m) => iss.body.append(fiSensLine(m)));
    // карта для GPS: собираем широту/долготу из отдельных полей
    const lat = sens.find((m) => /latitude/i.test(m.key));
    const lon = sens.find((m) => /longitude/i.test(m.key));
    if (lat && lon) {
      const la = parseFloat(lat.value), lo = parseFloat(lon.value);
      if (isFinite(la) && isFinite(lo)) {
        iss.body.append(el("div", { style: "margin-top:6px" },
          el("span", { class: "mono", style: "margin-right:10px" }, `${la.toFixed(6)}, ${lo.toFixed(6)}`),
          el("a", { class: "act", href: `https://www.openstreetmap.org/?mlat=${la}&mlon=${lo}#map=15/${la}/${lo}`, target: "_blank", rel: "noopener" }, "📍 показать на карте (OSM)")));
      }
    }
    wrap.append(iss.block);
  } else if (d.format !== "unknown") {
    wrap.append(finding("ok", "", "Приватных метаданных (GPS, автор, устройство) не обнаружено."));
  }

  if (d.metadata.length) {
    const p = rblock(rbTitle("Все метаданные", d.metadata.length), { accent: "#22d3ee" });
    const table = el("table", { class: "dtable" });
    table.append(el("thead", {}, el("tr", {}, el("th", {}, "поле"), el("th", {}, "категория"), el("th", {}, "значение"))));
    const tb = el("tbody", {});
    d.metadata.forEach((m) => tb.append(el("tr", {},
      el("td", { style: "white-space:nowrap" }, `${m.label || m.key}${m.sensitive ? " ⚠" : ""}`),
      el("td", { class: "muted", style: "white-space:nowrap" }, FI_CAT[m.category] || m.category),
      el("td", { style: "max-width:520px" }, fiMetaValue(m)))));
    table.append(tb);
    p.body.append(el("div", { class: "dtable-wrap" }, table));
    wrap.append(p.block);
  }

  // Очистка: показываем ЗАРАНЕЕ что уйдёт / что останется / чего формат не умеет
  const actions = rblock(rbTitle("Очистка метаданных"), { accent: "#c084fc" });
  if (d.can_sanitize) {
    if (sens.length) {
      actions.body.append(el("div", { class: "rb-note", style: "margin-top:0" }, "Будут удалены приватные поля:"));
      actions.body.append(el("div", { class: "chips" }, ...sens.map((m) => el("span", { class: "chip" }, m.label || m.key))));
    } else {
      actions.body.append(el("div", { class: "rb-note", style: "margin-top:0" }, "Приватных полей нет, но можно вычистить все текстовые метаданные."));
    }
    actions.body.append(el("div", { class: "muted", style: "margin:6px 0" }, "Пиксели и размер изображения не меняются. Оригинал не трогаем — отдаём очищенную копию."));
    actions.body.append(el("button", { class: "btn", onclick: runSanitize }, "Очистить и проверить →"));
  } else {
    actions.body.append(el("div", { class: "rb-note", style: "margin-top:0" },
      `Для формата ${d.format.toUpperCase()} безопасная очистка пока не поддержана — мы не удаляем то, что не умеем удалить надёжно, чтобы не испортить документ.`));
  }
  wrap.append(actions.block);
  wrap.append(el("div", { id: "fiClean", style: "margin-top:14px" }));
  return wrap;
}
async function runSanitize() {
  const fd = new FormData(); fd.append("file", fiFile);
  await withState($("#fiClean"), "Чистим копию и перепроверяем…", async () => {
    const res = await fetch("/api/file/sanitize", { method: "POST", body: fd });
    if (!res.ok) { const j = await res.json().catch(() => null); throw new ApiError(j?.error?.message || "Ошибка"); }
    const d = await res.json();
    const wrap = el("div", {});
    const afterSens = (d.after.sensitive_metadata || []).length;
    const ok = afterSens === 0;
    wrap.append(el("div", { class: `verdict ${ok ? "ok" : "warn"}` },
      el("span", { class: "big" }, ok ? "✓" : "⚠"),
      el("span", {}, ok
        ? `Очищено. Убрано полей: ${d.removed_fields.length}. Приватных данных в копии не осталось.`
        : `Убрано полей: ${d.removed_fields.length}, но ${afterSens} приватных поле(й) формат сохранил.`)));
    if (d.removed_fields.length) {
      wrap.append(el("div", { class: "rb-note" }, "Удалено:"));
      wrap.append(el("div", { class: "chips" }, ...d.removed_fields.map((f) => el("span", { class: "chip" }, f))));
    }
    // before/after — перепроверка результата
    wrap.append(el("div", { class: "chips", style: "margin-top:8px" },
      el("span", { class: "muted" }, `метаданных: ${d.before.metadata.length} → ${d.after.metadata.length}`),
      el("span", { class: "muted" }, `приватных: ${(d.before.sensitive_metadata || []).length} → ${afterSens}`)));
    if (!ok && d.after.sensitive_metadata) {
      d.after.sensitive_metadata.forEach((m) => wrap.append(finding("warn", FI_CAT[m.category] || m.category, `осталось: ${m.label || m.key}`)));
    }
    wrap.append(el("div", { class: "row", style: "margin-top:10px" },
      el("a", { class: "btn", href: "#", onclick: (e) => { e.preventDefault(); downloadClean(); } }, "↓ Скачать очищенную копию")));
    return wrap;
  });
}
async function downloadClean() {
  const fd = new FormData(); fd.append("file", fiFile);
  const res = await fetch("/api/file/sanitize?download=true", { method: "POST", body: fd });
  if (!res.ok) { toast("Не удалось", "error"); return; }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: fiFile.name.replace(/(\.[^.]+)$/, ".clean$1") });
  document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  toast("Скачивается", "success");
}
function fmtBytes(n) { if (n < 1024) return n + " B"; if (n < 1048576) return (n / 1024).toFixed(1) + " KB"; return (n / 1048576).toFixed(1) + " MB"; }


// =====================================================================
// UNICODE · анализ + Clean Copy / Normalize / Escape (/api/unicode2)
// =====================================================================
let uniReady = false;
function initUnicode2Once() {
  if (uniReady) return;
  uniReady = true;
  $("#u2Go") && $("#u2Go").addEventListener("click", runUnicode2);
  $("#u2Clean") && $("#u2Clean").addEventListener("click", () => u2Action("clean"));
  $("#u2Escape") && $("#u2Escape").addEventListener("click", () => u2Action("escape"));
  $("#u2Unescape") && $("#u2Unescape").addEventListener("click", () => u2Action("unescape"));
  $("#u2Norm") && $("#u2Norm").addEventListener("click", () => u2Action("normalize"));
}
async function u2post(path, body) {
  return api("/api/unicode2/" + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
}
async function runUnicode2() {
  const text = $("#u2Text").value;
  if (!text) { toast("Вставьте текст", "error"); return; }
  await withState($("#u2Out"), "Анализируем…", async () => {
    const d = await u2post("inspect", { text });
    return renderUnicode2(text, d);
  });
}
function renderUnicode2(text, d) {
  const wrap = el("div", {});
  wrap.append(el("div", { class: "chips", style: "margin-bottom:12px" },
    el("span", { class: "chip active" }, `символов: ${d.length}`),
    el("span", { class: "chip" }, `байт: ${d.bytes}`),
    el("span", { class: `chip ${d.issues.length ? "" : "active"}` }, `находок: ${d.issues.length}`),
    el("span", { class: "chip" }, d.normalization.is_nfc ? "NFC ✓" : "не NFC ✕")));

  // подсветка текста
  const render = el("div", { class: "uni-render" });
  const byIndex = {};
  d.issues.forEach((i) => (byIndex[i.index] = i));
  [...text].forEach((ch, i) => {
    const iss = byIndex[i];
    if (iss) {
      const shown = /\s|\p{C}/u.test(ch) ? `[${iss.codepoint}]` : ch;
      render.append(el("span", { class: "uni-mark alert", title: `${iss.codepoint} ${iss.name} · ${iss.kind} → ${iss.action}` }, shown));
    } else render.append(document.createTextNode(ch));
  });
  wrap.append(el("div", { class: "panel" }, el("h3", {}, "Текст с подсветкой"), render,
    el("div", { class: "muted", style: "margin-top:8px" }, "Наведи на подсвеченный символ — код, тип и что с ним сделает Clean Copy.")));

  if (d.mixed_script && d.mixed_script.length) {
    const p = el("div", { class: "panel" }, el("h3", {}, "Смешанные системы письма"));
    d.mixed_script.forEach((m) => p.append(finding("warn", "", `«${m.word}» — ${(m.scripts || []).join(" + ")}`)));
    wrap.append(p);
  }
  if (d.issues.length) {
    const p = el("div", { class: "panel" }, el("h3", {}, "Находки"));
    d.issues.slice(0, 100).forEach((i) => p.append(finding(i.action === "keep" ? "info" : "warn", i.codepoint, `${i.name} · ${i.kind} → ${i.action}`)));
    wrap.append(p);
  }
  return wrap;
}
async function u2Action(kind) {
  const text = $("#u2Text").value;
  if (!text) { toast("Вставьте текст", "error"); return; }
  let d, result, note = "";
  try {
    if (kind === "clean") { d = await u2post("clean", { text }); result = d.cleaned; note = `изменений: ${(d.changes || []).length}`; }
    else if (kind === "normalize") { d = await u2post("normalize", { text, form: $("#u2Form").value }); result = d.result; note = "форма " + $("#u2Form").value; }
    else if (kind === "escape") { d = await u2post("escape", { text, mode: "escape" }); result = d.result; }
    else if (kind === "unescape") { d = await u2post("escape", { text, mode: "unescape" }); result = d.result; }
  } catch (e) { toast(e.message, "error"); return; }
  const out = $("#u2Result");
  out.value = result;
  // preview изменений для clean
  const box = $("#u2ChangeNote");
  if (box) box.textContent = note;
  toast("Готово" + (note ? " · " + note : ""), "success");
  if (kind === "clean" && window.ForitKit) {
    render($("#u2Diff"), ForitKit.diffView(text, result));
  }
}
function u2Copy() {
  const v = $("#u2Result").value;
  navigator.clipboard.writeText(v).then(() => toast("Скопировано", "success")).catch(() => { $("#u2Result").select(); document.execCommand("copy"); toast("Скопировано", "success"); });
}


// =====================================================================
// PRINT · подготовка к печати (frontend-only)
// =====================================================================
let printReady = false;
const PR_MARGIN = { narrow: "12mm", normal: "20mm", wide: "30mm" };
function initPrintOnce() {
  if (printReady) return;
  printReady = true;
  ["prTitle", "prText", "prPaper", "prOrient", "prMargin", "prFont", "prHeader", "prDate", "prPageNo"]
    .forEach((id) => { const n = $("#" + id); if (n) n.addEventListener("input", renderPrintPreview); });
  const btn = $("#prPrint");
  if (btn) btn.addEventListener("click", doPrint);
  renderPrintPreview();
}
function printSettings() {
  return {
    title: $("#prTitle").value.trim(),
    text: $("#prText").value,
    paper: $("#prPaper").value,
    orient: $("#prOrient").value,
    margin: PR_MARGIN[$("#prMargin").value] || "20mm",
    font: $("#prFont").value,
    header: $("#prHeader").checked,
    date: $("#prDate").checked,
    pageNo: $("#prPageNo").checked,
  };
}
function renderPrintPreview() {
  const s = printSettings();
  const page = $("#prPreview");
  if (!page) return;
  // размеры листа для предпросмотра (мм → примерный масштаб)
  const dims = s.paper === "Letter" ? [216, 279] : [210, 297];
  const [w, h] = s.orient === "landscape" ? [dims[1], dims[0]] : dims;
  page.style.width = w + "mm";
  page.style.minHeight = h + "mm";
  page.style.padding = s.margin;
  page.style.fontSize = s.font + "px";
  page.replaceChildren();
  if (s.header && s.title) page.append(el("h1", { class: "pr-h1" }, s.title));
  const meta = [];
  if (s.date) meta.push(new Date().toLocaleDateString("ru-RU"));
  if (meta.length) page.append(el("div", { class: "pr-meta" }, meta.join(" · ")));
  const body = el("div", { class: "pr-body" });
  (s.text || "Вставьте текст слева — здесь появится предпросмотр печатной страницы.").split(/\n{2,}/).forEach((para) => {
    body.append(el("p", {}, para));
  });
  page.append(body);
}
function doPrint() {
  const s = printSettings();
  const win = window.open("", "_blank");
  if (!win) { toast("Браузер заблокировал окно печати", "error"); return; }
  const dims = s.paper === "Letter" ? "letter" : "A4";
  const paras = (s.text || "").split(/\n{2,}/).map((p) => `<p>${escHtml(p)}</p>`).join("");
  const header = s.header && s.title ? `<h1>${escHtml(s.title)}</h1>` : "";
  const meta = s.date ? `<div class="meta">${new Date().toLocaleDateString("ru-RU")}</div>` : "";
  const foot = s.pageNo ? "" : "";
  win.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${escHtml(s.title || "Печать")}</title>
    <style>
      @page { size: ${dims} ${s.orient}; margin: ${s.margin}; }
      html,body{margin:0}
      body{font:${s.font}px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#111}
      h1{font-size:1.6em;margin:0 0 .4em}
      .meta{color:#666;font-size:.82em;margin-bottom:1em;border-bottom:1px solid #ddd;padding-bottom:.4em}
      p{margin:0 0 .8em;white-space:pre-wrap;word-break:break-word}
      @media print { .noprint{display:none} }
    </style></head><body>${header}${meta}${paras}${foot}</body></html>`);
  win.document.close();
  win.focus();
  setTimeout(() => { win.print(); }, 250);
}
function escHtml(s) { return String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }


// =====================================================================
// BATCH RENAME · план old→new (превью) → ZIP (/api/rename)
// =====================================================================
let brReady = false;
let brFiles = [];       // File[] (если выбраны реальные файлы)
let brNames = [];       // list[str] имён (из файлов или вставленных)
function initBatchRenameOnce() {
  if (brReady) return;
  brReady = true;
  $("#brFiles") && $("#brFiles").addEventListener("change", (e) => {
    brFiles = [...e.target.files];
    brNames = brFiles.map((f) => f.name);
    $("#brNames").value = brNames.join("\n");
    brPreview();
  });
  $("#brNames") && $("#brNames").addEventListener("input", () => {
    brNames = $("#brNames").value.split("\n").map((s) => s.trim()).filter(Boolean);
    brPreview();
  });
  $("#brAddRule") && $("#brAddRule").addEventListener("click", () => { brAddRuleRow(); brPreview(); });
  $("#brApply") && $("#brApply").addEventListener("click", brApply);
  brAddRuleRow();
}
const BR_OPS = [
  ["prefix", "Префикс"], ["suffix", "Суффикс"], ["replace", "Найти/заменить"],
  ["regex_replace", "Regex"], ["lowercase", "нижний регистр"], ["uppercase", "ВЕРХНИЙ"],
  ["title", "Каждое Слово"], ["numbering", "Нумерация"],
];
function brAddRuleRow() {
  const tb = $("#brRules");
  if (!tb) return;
  const op = el("select", { class: "br-op", onchange: brPreview }, ...BR_OPS.map(([v, l]) => el("option", { value: v }, l)));
  const p1 = el("input", { class: "br-p1", placeholder: "текст / find / pattern / start", oninput: brPreview });
  const p2 = el("input", { class: "br-p2", placeholder: "replace / step", oninput: brPreview });
  const del = el("button", { class: "act plain", onclick: (e) => { e.target.closest("tr").remove(); brPreview(); } }, "✕");
  tb.append(el("tr", {}, el("td", {}, op), el("td", {}, p1), el("td", {}, p2), el("td", {}, del)));
}
function brCollectRules() {
  return $$("#brRules tr").map((tr) => {
    const op = $(".br-op", tr).value, a = $(".br-p1", tr).value, b = $(".br-p2", tr).value;
    if (op === "prefix" || op === "suffix") return { operation: op, params: { text: a } };
    if (op === "replace") return { operation: op, params: { find: a, replace: b } };
    if (op === "regex_replace") return { operation: op, params: { pattern: a, replacement: b } };
    if (op === "numbering") return { operation: op, params: { start: parseInt(a) || 1, step: parseInt(b) || 1, padding: 3, position: "prefix" } };
    return { operation: op, params: {} };
  });
}
async function brPreview() {
  if (!brNames.length) { $("#brOut") && $("#brOut").replaceChildren(); return; }
  let plan;
  try { plan = await api("/api/rename/plan", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ names: brNames, rules: brCollectRules() }) }); }
  catch (e) { render($("#brOut"), State.error(e)); return; }
  render($("#brOut"), renderRenamePlan(plan));
}
function renderRenamePlan(plan) {
  const wrap = el("div", {});
  const su = plan.summary || {};
  wrap.append(el("div", { class: "chips", style: "margin-bottom:10px" },
    el("span", { class: "chip active" }, `файлов: ${su.total || 0}`),
    el("span", { class: "chip" }, `изменится: ${su.changed || 0}`),
    su.conflicts ? el("span", { class: "chip" }, `конфликтов: ${su.conflicts}`) : null,
    su.errors ? el("span", { class: "chip" }, `ошибок: ${su.errors}`) : null,
    el("span", { class: `chip ${plan.valid ? "active" : ""}` }, plan.valid ? "готово к применению" : "есть проблемы")));
  const table = el("table", { class: "dtable" });
  table.append(el("thead", {}, el("tr", {}, el("th", {}, "было"), el("th", {}, "→ станет"), el("th", {}, ""))));
  const tb = el("tbody", {});
  (plan.items || []).slice(0, 300).forEach((it) => tb.append(el("tr", {},
    el("td", { title: it.old_name }, esc(it.old_name)),
    el("td", { title: it.new_name, style: it.errors.length ? "color:var(--alert)" : (it.changed ? "color:var(--ok)" : "") }, esc(it.new_name)),
    el("td", { class: "muted" }, it.errors.length ? esc(it.errors.join("; ")) : (it.changed ? "" : "без изменений")))));
  table.append(tb);
  wrap.append(el("div", { class: "dtable-wrap" }, table));
  wrap.append(el("div", { class: "rb-note", style: "margin-top:8px" }, "Оригиналы на компьютере не меняются — «Применить» отдаёт ZIP с переименованными файлами."));
  return wrap;
}
async function brApply() {
  if (!brFiles.length) { toast("Выберите файлы (не только имена) для ZIP", "error"); return; }
  const fd = new FormData();
  brFiles.forEach((f) => fd.append("files", f));
  fd.append("rules", JSON.stringify(brCollectRules()));
  toast("Готовим ZIP…");
  try {
    const res = await fetch("/api/rename/apply", { method: "POST", body: fd });
    if (res.status === 400) { const j = await res.json(); render($("#brOut"), renderRenamePlan(j.plan || {})); toast("План невалиден — исправьте", "error"); return; }
    if (!res.ok) { toast("Не удалось применить", "error"); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = el("a", { href: url, download: "renamed.zip" });
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    toast("ZIP скачивается", "success");
  } catch (e) { toast(String(e), "error"); }
}

// ---------- старт ----------
navigate(location.hash.slice(1) || "home");
buildChaosUrl();
