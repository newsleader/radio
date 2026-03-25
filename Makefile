.PHONY: build up down logs restart shell reload rebuild

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f radio

restart:
	docker compose restart radio

shell:
	docker compose exec radio bash

# Restart without rebuilding (works because code is volume-mounted)
reload:
	docker compose restart radio

# Full teardown + rebuild + start
rebuild:
	docker compose down && docker compose build && docker compose up -d

# Quick health check
health:
	curl -s http://localhost:8000/health | python3 -m json.tool

# Stream test (requires ffmpeg locally)
test-stream:
	ffplay -nodisp -autoexit http://localhost:8000/stream &
