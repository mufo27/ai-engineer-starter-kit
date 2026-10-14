# AI Engineer Starter Kit — developer tasks
.PHONY: help up down logs test lint eval demo build clean

help:            ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:              ## Build + start the full stack (api, web, db, redis)
	docker compose up -d --build

down:            ## Stop the stack (keeps data volume)
	docker compose down

logs:            ## Tail api logs
	docker compose logs -f api

test:            ## Run backend test suite (no Docker needed)
	cd backend && python -m pytest -q

lint:            ## Ruff + import sort check
	cd backend && ruff check app tests

eval:            ## Run RAG eval harness (mock, offline)
	python eval/run.py --min-score 0.8

demo:            ## End-to-end demo: health -> ingest -> ask -> usage
	bash scripts/demo.sh

build:           ## Build docker images only
	docker compose build

clean:           ## Stop and remove volumes (destroys DB data)
	docker compose down -v
