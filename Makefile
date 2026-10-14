.PHONY: install test demo lint server console docker-build docker-up k8s-apply clean

install:
	pip install -e ".[dev]"

test:
	python -m pytest -q

demo:
	python -m prof demo

server:
	PROF_DEMO=1 python -m prof gateway

console:
	PROF_DEMO=1 python -m prof gateway & sleep 2; open http://127.0.0.1:8091/console/ 2>/dev/null || xdg-open http://127.0.0.1:8091/console/; wait

docker-build:
	docker build -t prof-gateway:0.1.0 .

docker-up:
	cp -n configs/prof.env.example configs/prof.env 2>/dev/null || true
	docker compose up -d --build

k8s-apply:
	kubectl apply -f deploy/k8s.yaml

lint:
	python -m ruff check prof tests 2>/dev/null || python -m py_compile prof/*.py

bench:
	python bench/bench.py

clean:
	rm -rf __pycache__ prof/__pycache__ tests/__pycache__ .pytest_cache *.egg-info
