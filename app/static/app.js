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
const VIEWS = ["home", "about", "harvester", "finder", "burner", "drift", "unicode", "chaos"];
let currentView = null, prevView = null;
function navigate(view) {
  if (!VIEWS.includes(view)) view = "home";
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
  if (view === "chaos") buildChaosUrl();
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
const TOOLS_META = {
  harvester: { title: "Web Harvester", sub: "Достань данные со страниц", img: "harvester", accent: "#22d3ee", tags: ["HTML", "Table", "Dataset"] },
  finder: { title: "API Finder", sub: "Найди бесплатные API под задачу", img: "finder", accent: "#a855f7", tags: ["API", "Free tier", "Integrations"] },
  burner: { title: "Data Burner", sub: "Создай синтетику с дефектами", img: "burner", accent: "#fb7132", tags: ["Dataset", "Anomalies", "Test"] },
  drift: { title: "Drift Lab", sub: "Сравни версии данных", img: "drift", accent: "#3b82f6", tags: ["Drift", "Analytics", "Insights"] },
  unicode: { title: "Unicode Crime Lab", sub: "Найди невидимые проблемы в тексте", img: "unicode", accent: "#c084fc", tags: ["Text", "Unicode", "Validation"] },
  chaos: { title: "Chaos API", sub: "Сломай свой клиент раньше пользователей", img: "chaos", accent: "#f43f5e", tags: ["HTTP", "Errors", "Resilience"] },
};
// ---------- О проекте / Как это работает ----------
const ABOUT = [
  { id: "harvester", name: "Web Harvester", accent: "#22d3ee",
    what: "Принимает ссылку на публичную страницу и вытаскивает всё структурированное: таблицы, повторяющиеся карточки-сущности, ссылки, картинки, формы, метаданные, JSON-LD и кандидатов в открытые API.",
    why: "Быстро превратить любую веб-страницу в датасет, не открывая DevTools и не пиша парсер под каждый сайт.",
    example: "Дал ссылку на статью со списком стран → получил CSV с таблицей ВВП одним кликом." },
  { id: "finder", name: "API Finder", accent: "#a855f7",
    what: "Ищет бесплатные публичные API по теме на человеческом языке. Карточка каждого API: авторизация, тип бесплатности, лимиты, CORS, форматы, ссылка на документацию и дата проверки.",
    why: "Найти источник данных, которым можно пользоваться бесплатно прямо сейчас, а не открывать 5000 каталогов и натыкаться на $49/мес.",
    example: "Ввёл «погода» → Open-Meteo без ключа, с документацией и живой проверкой доступности." },
  { id: "burner", name: "Data Burner", accent: "#fb7132",
    what: "Генерирует реалистичные синтетические выгрузки с управляемыми дефектами: пропуски, выбросы, дубли, перекос классов, сломанные даты, unicode-ловушки, дрейф.",
    why: "Протестировать свой пайплайн на данных, которые выглядят правдоподобно, но содержат именно ту грязь, которую надо проверить.",
    example: "Собрал пару reference/current с дрейфом и сразу отправил её в Drift Lab." },
  { id: "drift", name: "Drift Lab", accent: "#3b82f6",
    what: "Сравнивает две выгрузки и объясняет расхождения: смена схемы, распределения (PSI, KS-тест), категории (χ², новые/пропавшие значения), рост пропусков, пересечение идентификаторов.",
    why: "Понять, что именно изменилось между версиями данных — с человеческим объяснением, а не сухим «drift = 0.42».",
    example: "Залил вчерашний и сегодняшний экспорт → увидел, что income начал пропадать, а age сменил тип." },
  { id: "unicode", name: "Unicode Crime Lab", accent: "#c084fc",
    what: "Вскрывает невидимый текстовый мусор: zero-width символы, NBSP, управляющие знаки, разницу NFC/NFD и кириллицу под видом латиницы — с подсветкой прямо в тексте.",
    why: "Найти причину, почему «одинаковые» строки не равны, JOIN не сходится, а поиск не находит очевидное.",
    example: "Вставил логин из формы → нашёл zero-width в конце, из-за которого не проходила авторизация." },
  { id: "chaos", name: "Chaos API", accent: "#f43f5e",
    what: "Эндпоинт, который намеренно ведёт себя плохо: задержки, произвольные 5xx, битый JSON, обрыв соединения, сломанная пагинация, гигантский ответ, враждебные заголовки.",
    why: "Проверить, переживёт ли твой фронтенд/бэкенд реальную жизнь, до того как это проверят пользователи.",
    example: "Собрал URL с задержкой 5с и 503 → проверил, корректно ли клиент показывает ошибку и ретраит." },
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
    card.innerHTML =
      `<div class="art"><span class="num">0${i + 1}</span>` +
      `<img src="/brand/tools/${m.img}.png" alt="${esc(m.title)}" loading="lazy"></div>` +
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

// ---------- старт ----------
navigate(location.hash.slice(1) || "home");
buildChaosUrl();
