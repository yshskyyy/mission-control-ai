.PHONY: run worker queue-worker migrate frontend-install frontend-dev frontend-build frontend-check test eval check

run:
	./venv/bin/python -m uvicorn app.main:app --reload

worker:
	./venv/bin/python -m app.worker

queue-worker:
	./venv/bin/rq worker --with-scheduler --url "$${REDIS_URL:-redis://127.0.0.1:6379/0}" mission-control

migrate:
	./venv/bin/python -m alembic upgrade head

frontend-install:
	npm --prefix frontend ci

frontend-dev:
	npm --prefix frontend run dev

frontend-build:
	npm --prefix frontend run build

frontend-check:
	npm --prefix frontend run check

test:
	./venv/bin/python -m pytest -q

eval:
	./venv/bin/python -m evals.run --suite all

check:
	./venv/bin/python -m compileall -q app evals tests
	./venv/bin/python -m pytest -q
	./venv/bin/python -m evals.run --suite all
	npm --prefix frontend run check
	npm --prefix frontend run build
	git diff --check
