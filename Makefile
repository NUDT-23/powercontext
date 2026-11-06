SHELL := /bin/sh
COMPOSE := docker compose

.PHONY: up up-d down logs seed verify evidence reset shell ps

up:
	$(COMPOSE) up --build

up-d:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f app

ps:
	$(COMPOSE) ps

seed:
	$(COMPOSE) exec app python -m app.seed

verify:
	$(COMPOSE) exec app python -m app.verify

evidence:
	$(COMPOSE) exec app python -m app.export_evidence

reset:
	$(COMPOSE) down -v

shell:
	$(COMPOSE) exec app /bin/sh
