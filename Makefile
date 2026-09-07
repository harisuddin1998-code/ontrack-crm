# Makefile for ON TRACK ERP
.PHONY: help install dev-install prod-install migrate upgrade downgrade \
        seed init-db test lint format run-prod run-dev docker-up docker-down \
        clean backup

help:
	@echo "ON TRACK ERP - Available Commands"
	@echo "=================================="
	@echo "install          - Install production dependencies"
	@echo "dev-install      - Install development dependencies"
	@echo "prod-install     - Install production dependencies"
	@echo "migrate          - Create new database migration"
	@echo "upgrade          - Apply database migrations"
	@echo "downgrade        - Rollback last migration"
	@echo "init-db          - Initialize database"
	@echo "seed             - Seed database with initial data"
	@echo "run-dev          - Run development server"
	@echo "run-prod         - Run production server (gunicorn)"
	@echo "docker-up        - Start Docker containers"
	@echo "docker-down      - Stop Docker containers"
	@echo "test             - Run tests"
	@echo "lint             - Run code linting"
	@echo "format           - Format code with black"
	@echo "clean            - Clean build files"
	@echo "backup           - Backup database"

install:
	pip install -r requirements/base.txt

dev-install:
	pip install -r requirements/dev.txt

prod-install:
	pip install -r requirements/prod.txt

migrate:
	flask db migrate -m "$(message)"

upgrade:
	flask db upgrade

downgrade:
	flask db downgrade

init-db:
	python scripts/init_db.py

seed:
	python scripts/seed_data.py

run-dev:
	flask run --debug --host=0.0.0.0 --port=5000

run-prod:
	gunicorn -c deployment/gunicorn.conf.py wsgi:app

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

test:
	pytest tests/ -v --cov=src --cov-report=term

test-cov:
	pytest tests/ -v --cov=src --cov-report=html --cov-report=term

lint:
	flake8 src/ tests/
	mypy src/

format:
	black src/ tests/
	isort src/ tests/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf htmlcov
	rm -rf dist
	rm -rf build
	rm -rf *.egg-info

backup:
	python scripts/backup_db.py