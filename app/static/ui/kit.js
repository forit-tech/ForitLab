"use strict";
/* Forit Lab — переиспользуемые UI-примитивы для инструментов новой архитектуры.
   Vanilla, без сборки и зависимостей. Самодостаточно (свой DOM-хелпер), чтобы
   не зависеть от порядка загрузки app.js.

   Экспортирует window.ForitKit:
     tabs(items)          — прогрессивное раскрытие (Simple → Advanced → Raw)
     diffView(a, b)       — построчный before/after
     jsonTree(data)       — сворачиваемое дерево JSON
     progressBar()        — индикатор прогресса с setProgress/setLabel
     badge(kind, text)    — LOCAL / SERVER бейдж
     dialog(opts)         — модальное окно (нативный <dialog>, ловушка фокуса, Esc)
     popover(anchor,opts) — всплывающая подсказка (hover/focus/tap)
   Никакого разбора user-agent — поведение зависит от ForitCaps. */
(function () {
  const el = (tag, props, ...kids) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === "class") node.className = v;
      else if (k === "html") node.innerHTML = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return node;
  };

  // ---------- tabs / progressive disclosure ----------
  function tabs(items) {
    // items: [{id, label, render:()=>Node, advanced?:bool}]
    const tablist = el("div", { class: "fk-tabs", role: "tablist" });
    const panels = el("div", { class: "fk-tabpanels" });
    const state = { active: items[0] && items[0].id };
    const buttons = new Map();
    const panelNodes = new Map();

    function select(id) {
      state.active = id;
      buttons.forEach((btn, key) => {
        const on = key === id;
        btn.classList.toggle("active", on);
        btn.setAttribute("aria-selected", String(on));
        btn.tabIndex = on ? 0 : -1;
      });
      panelNodes.forEach((panel, key) => {
        panel.hidden = key !== id;
      });
    }

    items.forEach((item) => {
      const btn = el(
        "button",
        {
          class: "fk-tab" + (item.advanced ? " fk-tab-advanced" : ""),
          type: "button",
          role: "tab",
          "aria-selected": "false",
          onclick: () => select(item.id),
        },
        item.label
      );
      buttons.set(item.id, btn);
      tablist.append(btn);
      const panel = el("div", { class: "fk-tabpanel", role: "tabpanel" });
      panel.append(item.render());
      panelNodes.set(item.id, panel);
      panels.append(panel);
    });

    // клавиатура: стрелки между вкладками
    tablist.addEventListener("keydown", (e) => {
      const ids = items.map((i) => i.id);
      const idx = ids.indexOf(state.active);
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const next = ids[(idx + (e.key === "ArrowRight" ? 1 : ids.length - 1)) % ids.length];
        select(next);
        buttons.get(next).focus();
      }
    });

    if (state.active) select(state.active);
    return el("div", { class: "fk-tabswrap" }, tablist, panels);
  }

  // ---------- diff (построчный) ----------
  function diffLines(a, b) {
    const A = a.split("\n");
    const B = b.split("\n");
    const n = A.length;
    const m = B.length;
    // LCS
    const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
    for (let i = n - 1; i >= 0; i--)
      for (let j = m - 1; j >= 0; j--)
        dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const rows = [];
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (A[i] === B[j]) {
        rows.push({ type: "equal", text: A[i] });
        i++;
        j++;
      } else if (dp[i + 1][j] >= dp[i][j + 1]) {
        rows.push({ type: "del", text: A[i++] });
      } else {
        rows.push({ type: "add", text: B[j++] });
      }
    }
    while (i < n) rows.push({ type: "del", text: A[i++] });
    while (j < m) rows.push({ type: "add", text: B[j++] });
    return rows;
  }

  function diffView(a, b) {
    const wrap = el("div", { class: "fk-diff" });
    diffLines(String(a ?? ""), String(b ?? "")).forEach((row) => {
      const sign = row.type === "add" ? "+" : row.type === "del" ? "−" : " ";
      wrap.append(
        el("div", { class: "fk-diff-row fk-diff-" + row.type }, el("span", { class: "fk-diff-sign" }, sign), el("span", { class: "fk-diff-text" }, row.text))
      );
    });
    return wrap;
  }

  // ---------- json tree ----------
  function jsonTree(data) {
    function node(key, value) {
      const isObj = value && typeof value === "object";
      if (!isObj) {
        const t = value === null ? "null" : typeof value;
        return el(
          "div",
          { class: "fk-jt-leaf" },
          key !== null ? el("span", { class: "fk-jt-key" }, key + ": ") : null,
          el("span", { class: "fk-jt-val fk-jt-" + t }, JSON.stringify(value))
        );
      }
      const entries = Array.isArray(value)
        ? value.map((v, i) => [String(i), v])
        : Object.entries(value);
      const details = el("details", { class: "fk-jt-node", open: entries.length <= 20 ? "" : false });
      const label = Array.isArray(value) ? `[] ${entries.length}` : `{} ${entries.length}`;
      details.append(el("summary", {}, key !== null ? key + " " : "", el("span", { class: "fk-jt-count" }, label)));
      const body = el("div", { class: "fk-jt-children" });
      entries.forEach(([k, v]) => body.append(node(k, v)));
      details.append(body);
      return details;
    }
    return el("div", { class: "fk-jsontree" }, node(null, data));
  }

  // ---------- progress ----------
  function progressBar() {
    const fill = el("i", {});
    const label = el("span", { class: "fk-progress-label" });
    const bar = el("div", { class: "fk-progress" }, el("div", { class: "fk-progress-track" }, fill), label);
    bar.setProgress = (p) => {
      fill.style.width = Math.max(0, Math.min(1, p)) * 100 + "%";
    };
    bar.setLabel = (t) => {
      label.textContent = t;
    };
    return bar;
  }

  // ---------- badge ----------
  function badge(kind, text) {
    const local = kind === "local";
    return el(
      "span",
      { class: "fk-badge fk-badge-" + (local ? "local" : "server"), title: local ? "Данные не покидают устройство" : "Требуется сетевой запрос" },
      text || (local ? "LOCAL" : "SERVER")
    );
  }

  // ---------- dialog (модалка) ----------
  function dialog(opts) {
    opts = opts || {};
    const dlg = el("dialog", { class: "fk-modal" });
    const card = el("div", { class: "fk-modal-card" });
    if (opts.title) {
      card.append(
        el(
          "div",
          { class: "fk-modal-head" },
          el("h3", { class: "fk-modal-title" }, opts.title),
          el(
            "button",
            { class: "fk-modal-close", type: "button", "aria-label": "Закрыть", onclick: () => close() },
            "✕"
          )
        )
      );
    }
    const body = el("div", { class: "fk-modal-body" });
    if (opts.content) body.append(opts.content);
    card.append(body);
    dlg.append(card);

    let returnFocus = null;
    function open() {
      returnFocus = document.activeElement;
      document.body.append(dlg);
      if (dlg.showModal) dlg.showModal();
      else dlg.setAttribute("open", "");
      document.documentElement.classList.add("fk-modal-open");
    }
    function close() {
      if (dlg.open && dlg.close) dlg.close();
      else dlg.removeAttribute("open");
      document.documentElement.classList.remove("fk-modal-open");
      if (returnFocus && document.contains(returnFocus)) returnFocus.focus();
      dlg.remove();
    }
    dlg.addEventListener("click", (e) => {
      if (e.target === dlg) close();
    });
    dlg.addEventListener("cancel", () => {
      document.documentElement.classList.remove("fk-modal-open");
    });
    // ловушка фокуса
    dlg.addEventListener("keydown", (e) => {
      if (e.key !== "Tab") return;
      const f = [...dlg.querySelectorAll("button,a[href],input,select,textarea,[tabindex]:not([tabindex='-1'])")].filter(
        (n) => !n.disabled && n.getClientRects().length
      );
      if (!f.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });
    return { el: dlg, body, open, close };
  }

  // ---------- popover (подсказка) ----------
  function popover(anchor, opts) {
    opts = opts || {};
    const pop = el("div", { class: "fk-popover", role: "tooltip" });
    if (opts.content) pop.append(opts.content);
    else if (opts.text) pop.textContent = opts.text;
    const wrap = el("span", { class: "fk-popover-wrap" }, anchor, pop);
    const st = { pinned: false, hover: false, focus: false };
    function sync() {
      const on = st.pinned || st.hover || st.focus;
      pop.classList.toggle("open", on);
      anchor.setAttribute("aria-expanded", String(on));
    }
    anchor.setAttribute("aria-expanded", "false");
    anchor.addEventListener("click", () => {
      st.pinned = !st.pinned;
      sync();
    });
    wrap.addEventListener("pointerenter", (e) => {
      if (e.pointerType === "mouse") {
        st.hover = true;
        sync();
      }
    });
    wrap.addEventListener("pointerleave", (e) => {
      if (e.pointerType === "mouse") {
        st.hover = false;
        sync();
      }
    });
    anchor.addEventListener("focus", (e) => {
      if (e.target.matches(":focus-visible")) {
        st.focus = true;
        sync();
      }
    });
    anchor.addEventListener("blur", () => {
      st.focus = false;
      sync();
    });
    document.addEventListener("pointerdown", (e) => {
      if (st.pinned && !wrap.contains(e.target)) {
        st.pinned = false;
        sync();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && pop.classList.contains("open")) {
        st.pinned = st.hover = st.focus = false;
        sync();
      }
    });
    return wrap;
  }

  window.ForitKit = { el, tabs, diffView, diffLines, jsonTree, progressBar, badge, dialog, popover };
})();
