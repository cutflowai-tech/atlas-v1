.PHONY: doctor lint typecheck unit contract integration e2e test runtime-health

doctor:
	./scripts/atlas doctor

lint:
	ruff check src tests

typecheck:
	mypy src

unit:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_commander.py' -v

contract:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_contracts.py' -v

integration:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_integration.py' -v

e2e:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_e2e.py' -v

test: lint typecheck unit contract integration e2e
	find config contracts fixtures tasks -name '*.json' -type f -exec python3 -m json.tool {} \; >/dev/null

runtime-health:
	./scripts/runtime-health
