#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "Ошибка: задайте OPENROUTER_API_KEY перед запуском"
  exit 1
fi

python main.py --input objects_list --api-key "$OPENROUTER_API_KEY" --districts tatarstan_locations.json
python main.py --input objects_list_mini --api-key "$OPENROUTER_API_KEY" --districts tatarstan_locations.json

