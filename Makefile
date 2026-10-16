.PHONY: install run test docker up down logs doctor discover

# Usage: make run SENSOR=192.168.1.50
SENSOR ?=

install:
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"

run:
	.venv/bin/ouster-demo $(if $(SENSOR),--source $(SENSOR),)

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q

docker:
	docker build -t ouster-demo:latest .

up:
	OUSTER_SOURCE=$(SENSOR) docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

doctor:
	.venv/bin/ouster-demo doctor $(SENSOR) --sdk

discover:
	.venv/bin/ouster-demo discover
