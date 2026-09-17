"use strict";
/* Forit Lab — определение возможностей браузера (capability detection).
   Только feature-detection конкретных API. Никакого разбора userAgent:
   Batch/File Inspector должны включать функции по реальным возможностям,
   а не по названию браузера. */
(function () {
  const has = (probe) => {
    try {
      return !!probe();
    } catch (_e) {
      return false;
    }
  };

  const caps = {
    // File System Access API — реальный Apply в Batch (переименование/перемещение/undo)
    fileSystemAccess: has(() => window.showOpenFilePicker) && has(() => window.showDirectoryPicker),
    saveFilePicker: has(() => window.showSaveFilePicker),
    directoryPicker: has(() => window.showDirectoryPicker),
    // локальная работа с файлами
    fileReader: has(() => window.FileReader),
    dragAndDrop: "ondrop" in window,
    // криптография (стабильная псевдонимизация в Share Safe и т.п.)
    webCrypto: has(() => window.crypto && window.crypto.subtle),
    // тяжёлые клиентские движки (DuckDB-WASM/SheetJS появятся позже — по требованию)
    wasm: has(() => typeof WebAssembly === "object"),
    // мелочи
    clipboardWrite: has(() => navigator.clipboard && navigator.clipboard.writeText),
    structuredClone: has(() => typeof structuredClone === "function"),
    dialog: has(() => typeof HTMLDialogElement !== "undefined"),
  };

  // Человеческое объяснение, почему функция недоступна (для честного UI, без fake success).
  caps.explain = function (feature) {
    const map = {
      fileSystemAccess:
        "Прямое сохранение/переименование файлов недоступно в этом браузере. Доступны предпросмотр и выгрузка результата.",
      saveFilePicker: "Диалог сохранения файла недоступен — файл будет отдан обычной загрузкой.",
      directoryPicker: "Выбор папки недоступен в этом браузере.",
    };
    return map[feature] || "Эта возможность недоступна в текущем браузере.";
  };

  window.ForitCaps = caps;
})();
