.PHONY: install lint format typecheck test security compose-validate smoke deploy check backup-now all

VENV_BIN ?= $(shell poetry env info --path 2>/dev/null)/bin
PYTHON ?= $(VENV_BIN)/python
RUFF ?= $(VENV_BIN)/ruff
MYPY ?= $(VENV_BIN)/mypy
PYTEST ?= $(VENV_BIN)/pytest

install:
	poetry install

lint:
	$(RUFF) check src/ tests/

format:
	$(RUFF) format src/ tests/

typecheck:
	PYTHONPATH=src $(MYPY) src/

test:
	PYTHONPATH=src $(PYTEST) --cov=fritz_monitoring tests/

security:
	$(VENV_BIN)/pip-audit --skip-editable --desc --ignore-vuln PYSEC-2026-1845

compose-validate:
	mkdir -p secrets
	@test -f secrets/fritz_password.txt || echo "test" > secrets/fritz_password.txt
	@test -f secrets/grafana_admin_password.txt || echo "test" > secrets/grafana_admin_password.txt
	@test -f secrets/device_manager_admin_password.txt || echo "test" > secrets/device_manager_admin_password.txt
	@test -f secrets/device_manager_secret_key.txt || echo "test_secret_key" > secrets/device_manager_secret_key.txt
	docker compose -f compose.prod.yml config > /dev/null

smoke:
	chmod +x scripts/verify-production.sh
	./scripts/verify-production.sh

deploy:
	./scripts/deploy.sh

check:
	./scripts/deploy.sh --check

backup-now:
	docker compose -f compose.prod.yml --env-file .env.production run --rm backup once

all: lint typecheck test compose-validate
