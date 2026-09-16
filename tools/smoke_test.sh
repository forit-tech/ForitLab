#!/usr/bin/env bash
# Проверка развёрнутого сервиса.
#
#   bash tools/smoke_test.sh https://forit-quest.ru
#   bash tools/smoke_test.sh                        # по умолчанию localhost:8000
#
# Скрипт ничего не чинит — только показывает, что отвечает, а что нет.

set -uo pipefail

BASE="${1:-http://127.0.0.1:8000}"
PASSED=0
FAILED=0
BODY="$(mktemp)"
REPORT="$(mktemp)"
trap 'rm -f "$BODY" "$REPORT"' EXIT

check() {
  local method="$1" path="$2" expected="$3"
  local code
  code=$(curl -s -o "$BODY" -w '%{http_code}' -X "$method" "${BASE}${path}")
  if [ "$code" = "$expected" ]; then
    printf '  ok    %-6s %-34s %s\n' "$method" "$path" "$code"
    PASSED=$((PASSED + 1))
  else
    printf '  FAIL  %-6s %-34s %s (ожидали %s)\n' "$method" "$path" "$code" "$expected"
    head -c 200 "$BODY"
    echo
    FAILED=$((FAILED + 1))
  fi
}

echo "Проверяем ${BASE}"
echo

check GET / 200
check GET /health 200
check GET /api/status 200
check GET /api/tools 200
check GET /api/drift/limits 200
check GET /docs 200
check GET /openapi.json 200
check GET /api/drift/demo 200
check GET /api/drift/reports 200
check GET /api/drift/reports/no-such-report 404
check GET /no-such-path 404

SAMPLES="$(dirname "$0")/../data/samples"
if [ -f "${SAMPLES}/reference.csv" ] && [ -f "${SAMPLES}/current.csv" ]; then
  echo
  echo "Загрузка файлов (главная проверка лимитов хостинга):"
  curl -s -X POST "${BASE}/api/drift/reports" \
    -F "reference=@${SAMPLES}/reference.csv" \
    -F "current=@${SAMPLES}/current.csv" \
    -o "$REPORT" \
    -w '  HTTP %{http_code}  загружено %{size_upload} байт  за %{time_total}s\n'
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "
import json, sys
try:
    report = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception as exc:
    print('  не удалось разобрать ответ:', exc); sys.exit(0)
summary = report.get('summary', {})
print('  вердикт:', summary.get('verdict', report.get('error', '?')))
print('  хранилище:', report.get('storage'))
print('  время расчёта:', report.get('duration_ms'), 'мс')
" "$REPORT"
  fi
fi

echo
echo "Пройдено: ${PASSED}, провалено: ${FAILED}"
[ "$FAILED" -eq 0 ]
