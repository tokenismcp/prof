.PHONY: install test demo lint server clean

install:
	pip install -e ".[dev]"

test:
	python -m pytest -q

demo:
	python -m prof demo

server:
	PROF_DEMO=1 python -m prof gateway

lint:
	python -m ruff check prof tests 2>/dev/null || python -m py_compile prof/*.py

bench:
	python bench/bench.py

clean:
	rm -rf __pycache__ prof/__pycache__ tests/__pycache__ .pytest_cache *.egg-info
