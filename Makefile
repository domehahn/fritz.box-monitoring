.PHONY: help install build up down logs test lint format clean restart health

help:
	@echo "Fritz!Box Monitoring System - Available Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install      - Install Poetry dependencies"
	@echo "  make build        - Build Docker images"
	@echo ""
	@echo "Running:"
	@echo "  make up           - Start Docker Compose stack"
	@echo "  make down         - Stop Docker Compose stack"
	@echo "  make restart      - Restart Docker Compose stack"
	@echo "  make logs         - Show Docker Compose logs"
	@echo "  make health       - Check health of services"
	@echo ""
	@echo "Development:"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Run linting (ruff)"
	@echo "  make format       - Format code (black)"
	@echo "  make type-check   - Run type checking (mypy)"
	@echo "  make dev          - Run in development mode"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean        - Clean build artifacts and cache"
	@echo "  make env          - Create .env from template"
	@echo "  make metrics      - Show Prometheus metrics"

# Setup
install:
	poetry install

build:
	docker-compose build

env:
	cp .env.example .env
	@echo "Created .env - please update with your Fritz!Box credentials"

# Docker Compose
up:
	docker-compose up -d
	@echo "Stack started. Access:"
	@echo "  Grafana:      http://localhost:3000"
	@echo "  Prometheus:   http://localhost:9090"
	@echo "  Alertmanager: http://localhost:9093"
	@echo "  Exporter:     http://localhost:8000/metrics"

down:
	docker-compose down

restart: down up

logs:
	docker-compose logs -f

logs-exporter:
	docker-compose logs -f fritz_exporter

logs-prometheus:
	docker-compose logs -f prometheus

logs-grafana:
	docker-compose logs -f grafana

# Health Checks
health:
	@echo "Checking service health..."
	@echo ""
	@echo "Fritz Exporter:"
	@curl -s http://localhost:8000/health && echo " ✓" || echo " ✗"
	@echo ""
	@echo "Prometheus:"
	@curl -s http://localhost:9090/-/healthy && echo " ✓" || echo " ✗"
	@echo ""
	@echo "Grafana:"
	@curl -s http://localhost:3000/api/health && echo " ✓" || echo " ✗"

# Metrics
metrics:
	@curl -s http://localhost:8000/metrics | grep fritzbox

metrics-watch:
	@watch -n 5 'curl -s http://localhost:8000/metrics | grep fritzbox'

# Testing
test:
	poetry run pytest -v

test-cov:
	poetry run pytest --cov=src/fritz_monitoring --cov-report=html
	@echo "Coverage report generated: htmlcov/index.html"

# Code Quality
lint:
	poetry run ruff check src tests

format:
	poetry run black src tests

format-check:
	poetry run black --check src tests

type-check:
	poetry run mypy src

type-check-strict:
	poetry run mypy src --strict

code-quality: lint format-check type-check-strict

# Development
dev:
	poetry run fritz-monitor run --log-level DEBUG

# Cleanup
clean:
	find . -type d -name __pycache__ -exec rm -r {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -r {} +
	rm -rf build dist .pytest_cache .mypy_cache htmlcov .coverage
	docker-compose down -v

# Docker Shell
shell-exporter:
	docker-compose exec fritz_exporter /bin/bash

shell-prometheus:
	docker-compose exec prometheus /bin/sh

shell-grafana:
	docker-compose exec grafana /bin/bash

# Database
db-clean:
	docker-compose exec prometheus rm -rf /prometheus/*
	docker-compose exec grafana rm -rf /var/lib/grafana/*
	@echo "Database cleaned. Restart containers: make restart"

# Dependencies
update-deps:
	poetry update

show-deps:
	poetry show --tree

# Git
git-setup:
	pre-commit install

# Documentation
docs:
	@echo "Available Documentation:"
	@echo "  - README.md                   - Project overview"
	@echo "  - docs/architecture.md        - System architecture"
	@echo "  - docs/troubleshooting.md     - Troubleshooting guide"

# All in one
setup: env install build

start: build up health

all: setup start

# Info
info:
	@echo "Fritz!Box Monitoring System Information"
	@echo ""
	@echo "Project Structure:"
	@echo "  src/fritz_monitoring/  - Main source code"
	@echo "  tests/                 - Unit tests"
	@echo "  config/                - Configuration files"
	@echo "  docker/                - Docker files"
	@echo "  docs/                  - Documentation"
	@echo ""
	@echo "Services:"
	@echo "  - Fritz!Box Exporter:  :8000"
	@echo "  - Prometheus:          :9090"
	@echo "  - Grafana:             :3000"
	@echo "  - InfluxDB:            :8086"
	@echo "  - Node Exporter:       :9100"
	@echo "  - Alertmanager:        :9093"
