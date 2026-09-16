/* Общие SVG-мотивы инструментов Forit Lab.
   Цвета берутся из CSS-переменных страницы через классы (.mln / .mln2 / .mfl / .mfl2 / .mdim / .mtxt),
   поэтому один и тот же мотив адаптируется под палитру любого варианта. */

const MOTIFS = {
  // Web Harvester: дерево DOM-узлов сворачивается в строки датасета
  harvester: `
  <svg viewBox="0 0 320 130" class="motif" preserveAspectRatio="xMidYMid meet">
    <g class="mdim" fill="none" stroke-width="1.3">
      <path d="M60 26 L60 52 M60 40 H36 V64 M60 40 H84 V64"/>
      <path d="M36 64 V88 H24 M36 64 V88 H48 M84 64 V88 H72 M84 64 V88 H96"/>
    </g>
    <circle cx="60" cy="22" r="6" class="mfl2"/>
    <g class="mfl"><circle cx="36" cy="62" r="4.5"/><circle cx="84" cy="62" r="4.5"/>
      <circle cx="24" cy="90" r="3.5"/><circle cx="48" cy="90" r="3.5"/><circle cx="72" cy="90" r="3.5"/><circle cx="96" cy="90" r="3.5"/></g>
    <g class="mln" fill="none" stroke-width="1.4"><path d="M110 60 h26 M138 55 l8 5 -8 5" stroke-linejoin="round"/></g>
    <g transform="translate(168,24)">
      <rect x="0" y="0" width="132" height="82" rx="6" class="mpanel"/>
      <line x1="0" y1="20" x2="132" y2="20" class="mdim" stroke-width="1"/>
      <line x1="44" y1="0" x2="44" y2="82" class="mdim" stroke-width="1"/>
      <line x1="88" y1="0" x2="88" y2="82" class="mdim" stroke-width="1"/>
      <rect x="8" y="7" width="28" height="7" rx="2" class="mfl2"/>
      <g class="mfl" opacity="0.85">
        <rect x="8" y="28" width="26" height="6" rx="2"/><rect x="52" y="28" width="26" height="6" rx="2"/><rect x="96" y="28" width="26" height="6" rx="2"/>
        <rect x="8" y="45" width="26" height="6" rx="2"/><rect x="52" y="45" width="26" height="6" rx="2"/><rect x="96" y="45" width="26" height="6" rx="2"/>
        <rect x="8" y="62" width="26" height="6" rx="2"/><rect x="52" y="62" width="26" height="6" rx="2"/><rect x="96" y="62" width="26" height="6" rx="2"/>
      </g>
    </g>
  </svg>`,

  // API Finder: сеть источников вокруг центрального хаба
  finder: `
  <svg viewBox="0 0 320 130" class="motif" preserveAspectRatio="xMidYMid meet">
    <g class="mdim" stroke-width="1.2" fill="none">
      <line x1="160" y1="65" x2="70" y2="34"/><line x1="160" y1="65" x2="250" y2="34"/>
      <line x1="160" y1="65" x2="52" y2="96"/><line x1="160" y1="65" x2="268" y2="96"/>
      <line x1="160" y1="65" x2="118" y2="108"/><line x1="160" y1="65" x2="210" y2="24"/>
    </g>
    <circle cx="160" cy="65" r="18" class="mhub"/>
    <circle cx="160" cy="65" r="27" class="mdim" fill="none" stroke-width="1" opacity="0.5"/>
    <path d="M154 65 a6 6 0 1 1 9 4.5 l4 4" class="mln" fill="none" stroke-width="2" stroke-linecap="round"/>
    <g class="mnode">
      <circle cx="70" cy="34" r="7"/><circle cx="250" cy="34" r="7"/><circle cx="52" cy="96" r="6"/>
      <circle cx="268" cy="96" r="6"/><circle cx="118" cy="108" r="5"/><circle cx="210" cy="24" r="5"/>
    </g>
    <circle cx="250" cy="34" r="7" class="mfl2"/>
  </svg>`,

  // Data Burner: сетка датасета с подложенными дефектами
  burner: `
  <svg viewBox="0 0 320 130" class="motif" preserveAspectRatio="xMidYMid meet">
    <g transform="translate(92,16)">
      <rect x="0" y="0" width="136" height="98" rx="6" class="mpanel"/>
      <g class="mdim" stroke-width="1">
        <line x1="0" y1="24.5" x2="136" y2="24.5"/><line x1="0" y1="49" x2="136" y2="49"/><line x1="0" y1="73.5" x2="136" y2="73.5"/>
        <line x1="34" y1="0" x2="34" y2="98"/><line x1="68" y1="0" x2="68" y2="98"/><line x1="102" y1="0" x2="102" y2="98"/>
      </g>
      <g class="mfl" opacity="0.7">
        <rect x="6" y="8" width="20" height="7" rx="2"/><rect x="40" y="8" width="20" height="7" rx="2"/><rect x="108" y="8" width="20" height="7" rx="2"/>
        <rect x="6" y="33" width="20" height="7" rx="2"/><rect x="74" y="33" width="20" height="7" rx="2"/>
        <rect x="40" y="57" width="20" height="7" rx="2"/><rect x="108" y="57" width="20" height="7" rx="2"/>
        <rect x="6" y="82" width="20" height="7" rx="2"/><rect x="74" y="82" width="20" height="7" rx="2"/>
      </g>
      <g class="mburn">
        <rect x="72" y="6" width="24" height="13" rx="2"/>
        <rect x="38" y="31" width="24" height="13" rx="2"/>
        <rect x="106" y="80" width="24" height="13" rx="2"/>
      </g>
      <text x="80" y="16" class="mtxt" font-size="9" text-anchor="middle">NULL</text>
      <text x="46" y="41" class="mtxt" font-size="9" text-anchor="middle">∞</text>
    </g>
  </svg>`,

  // Drift Lab: две распределённые кривые (reference vs current)
  drift: `
  <svg viewBox="0 0 320 130" class="motif" preserveAspectRatio="xMidYMid meet">
    <line x1="40" y1="104" x2="280" y2="104" class="mdim" stroke-width="1.2"/>
    <path d="M40 104 C100 104 108 44 148 44 C188 44 196 104 256 104" class="mln" fill="none" stroke-width="2.2"/>
    <path d="M40 104 C120 104 132 58 176 58 C220 58 232 104 280 104" class="mln2" fill="none" stroke-width="2.2" stroke-dasharray="5 4"/>
    <g class="mfl" opacity="0.14"><path d="M40 104 C100 104 108 44 148 44 C188 44 196 104 256 104 Z"/></g>
    <g class="mfl2" opacity="0.12"><path d="M40 104 C120 104 132 58 176 58 C220 58 232 104 280 104 Z"/></g>
    <line x1="148" y1="44" x2="148" y2="104" class="mln" stroke-width="1" stroke-dasharray="2 3" opacity="0.6"/>
    <line x1="176" y1="58" x2="176" y2="104" class="mln2" stroke-width="1" stroke-dasharray="2 3" opacity="0.7"/>
    <path d="M150 30 h28 M172 26 l6 4 -6 4" class="mln2" fill="none" stroke-width="1.4" stroke-linejoin="round"/>
  </svg>`,

  // Unicode Crime Lab: глифы, codepoints, невидимый знак
  unicode: `
  <svg viewBox="0 0 320 130" class="motif" preserveAspectRatio="xMidYMid meet">
    <g font-family="ui-monospace, monospace">
      <text x="48" y="66" font-size="40" class="mtxt-strong">A</text>
      <text x="96" y="66" font-size="40" class="mtxt-strong">a</text>
      <rect x="140" y="30" width="34" height="46" rx="5" class="mghost" stroke-dasharray="4 3"/>
      <text x="157" y="88" font-size="9" class="mtxt2" text-anchor="middle">U+200B</text>
      <text x="196" y="66" font-size="40" class="mtxt-strong mfl2-text">е</text>
      <text x="244" y="66" font-size="40" class="mtxt-strong">o</text>
    </g>
    <g class="mdim" stroke-width="1"><line x1="40" y1="96" x2="280" y2="96"/></g>
    <g font-family="ui-monospace, monospace" font-size="8" class="mtxt2">
      <text x="58" y="112" text-anchor="middle">0041</text>
      <text x="106" y="112" text-anchor="middle">0061</text>
      <text x="206" y="112" text-anchor="middle" class="mfl2-text">0435</text>
      <text x="254" y="112" text-anchor="middle">006F</text>
    </g>
  </svg>`,

  // Chaos API: один запрос → несколько разных ответов
  chaos: `
  <svg viewBox="0 0 320 130" class="motif" preserveAspectRatio="xMidYMid meet">
    <rect x="20" y="54" width="52" height="22" rx="5" class="mpanel"/>
    <text x="46" y="69" font-size="9" class="mtxt" text-anchor="middle" font-family="ui-monospace,monospace">GET</text>
    <path d="M74 65 h34" class="mln" fill="none" stroke-width="1.6"/>
    <circle cx="116" cy="65" r="6" class="mhub"/>
    <g class="mln" fill="none" stroke-width="1.3" opacity="0.8">
      <path d="M122 63 C150 40 176 34 214 30"/>
      <path d="M122 65 h92"/>
      <path d="M122 67 C150 90 176 96 214 100"/>
    </g>
    <g font-family="ui-monospace,monospace" font-size="9">
      <rect x="214" y="20" width="86" height="20" rx="5" class="mchip-ok"/><text x="223" y="34" class="mtxt">200 OK</text>
      <rect x="214" y="55" width="86" height="20" rx="5" class="mchip-warn"/><text x="223" y="69" class="mtxt">503 ⚠</text>
      <rect x="214" y="90" width="86" height="20" rx="5" class="mchip-alert"/><text x="223" y="104" class="mtxt">{"broken</text>
    </g>
  </svg>`,
};

const TOOLS = [
  { id: "harvester", name: "Web Harvester", tag: "Достань данные со страницы по ссылке", short: "Достань данные со страниц", verb: "Перейти", href: "/#harvester", accent: "#22d3ee", tags: ["HTML", "Table", "Dataset"] },
  { id: "finder", name: "API Finder", tag: "Найди бесплатный публичный API под задачу", short: "Найди бесплатные API под задачу", verb: "Перейти", href: "/#finder", accent: "#a855f7", tags: ["API", "Free tier", "Integrations"] },
  { id: "burner", name: "Data Burner", tag: "Создай синтетику с управляемыми дефектами", short: "Создай синтетику с дефектами", verb: "Перейти", href: "/#burner", accent: "#fb7132", tags: ["Dataset", "Anomalies", "Test"] },
  { id: "drift", name: "Drift Lab", tag: "Сравни две выгрузки и найди расхождения", short: "Сравни версии данных", verb: "Перейти", href: "/#drift", accent: "#3b82f6", tags: ["Drift", "Analytics", "Insights"] },
  { id: "unicode", name: "Unicode Crime Lab", tag: "Раскопай невидимый текстовый мусор", short: "Найди невидимые проблемы в тексте", verb: "Перейти", href: "/#unicode", accent: "#c084fc", tags: ["Text", "Unicode", "Validation"] },
  { id: "chaos", name: "Chaos API", tag: "Сломай свой HTTP-клиент раньше пользователей", short: "Сломай свой клиент раньше пользователей", verb: "Перейти", href: "/#chaos", accent: "#f43f5e", tags: ["HTTP", "Errors", "Resilience"] },
];

const PIPELINE = [
  { k: "finder", t: "Найти источник" },
  { k: "harvester", t: "Получить данные" },
  { k: "burner", t: "Создать / испортить" },
  { k: "unicode", t: "Исследовать" },
  { k: "drift", t: "Сравнить" },
  { k: "chaos", t: "Проверить клиент" },
];

if (typeof window !== "undefined") { window.MOTIFS = MOTIFS; window.TOOLS = TOOLS; window.PIPELINE = PIPELINE; }
