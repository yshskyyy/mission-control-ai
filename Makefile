.PHONY: run test check

run:
	./venv/bin/uvicorn app.main:app --reload

test:
	./venv/bin/python -m pytest -q

check:
	./venv/bin/python -m compileall -q app tests
	git diff --check
