.PHONY: dev api ui test build-ui sidecar verify smoke contracts lint lint-probe pack-new

PY ?= python

dev:  ## 一键开发（Windows 用 scripts/dev.ps1）
	bash scripts/dev.sh

api:
	$(PY) -m uvicorn main:app --app-dir api --port 8787 --reload

ui:
	cd ui && npm run dev

test:
	$(PY) -m pytest

build-ui:
	cd ui && npm run build

contracts:
	$(PY) tools/export_contracts.py

smoke:
	$(PY) tools/smoke_p0.py

lint:  ## 示例包 strict lint
	$(PY) tools/pack.py lint packs/night-convenience-store --strict

lint-probe:  ## 第二题材探针包 strict lint
	$(PY) tools/pack.py lint packs/probe-signal-station --strict

pack-new:  ## 生成空内容包：make pack-new DIR=build/demo ID=demo TITLE="演示"
	$(PY) tools/pack.py new $(DIR) --id $(ID) --title "$(TITLE)"

sidecar:
	$(PY) -m PyInstaller --noconfirm --clean --onefile --name rpg-sidecar \
	  --distpath dist --workpath build/pyinstaller --specpath build \
	  --add-data "packs;packs" --add-data "ui/dist;ui/dist" \
	  --paths core --paths gateway --paths content api/main.py

verify: contracts build-ui test smoke
