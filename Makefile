.PHONY: install lint format typecheck test security compose-validate smoke all

VENV_BIN ?= /Users/dominikhahn/Library/Caches/pypoetry/virtualenvs/fritz-box-monitoring--jVEQFYE-py3.14/bin
PYTHON ?= $(VENV_BIN)/python
RUFF ?= $(VENV_BIN)/ruff
MYPY ?= $(VENV_BIN)/mypy
PYTEST ?= $(VENV_BIN)/pytest
POETRY ?= poetry

install:
	pip install -e ../fritz-avm-client
	$(POETRY) install

lint:
	$(RUFF) check src/ tests/

format:
	$(RUFF) format src/ tests/

typecheck:
	PYTHONPATH=src $(MYPY) src/

test:
	PYTHONPATH=src $(PYTEST) --cov=fritz_monitoring tests/

security:
	pip-audit

compose-validate:
	mkdir -p secrets
	@test -f secrets/fritz_password.txt || echo "test" > secrets/fritz_password.txt
	@test -f secrets/grafana_admin_password.txt || echo "test" > secrets/grafana_admin_password.txt
	@test -f secrets/device_manager_admin_password.txt || echo "test" > secrets/device_manager_admin_password.txt
	docker compose -f compose.prod.yml config > /dev/null

smoke:
	chmod +x scripts/verify-production.sh
	./scripts/verify-production.sh

all: lint typecheck test compose-validate

