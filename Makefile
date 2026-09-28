.PHONY: doctor lint typecheck unit contract integration e2e ui-fixture ui-fixture-evidence web-demo test runtime-health

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

ui-fixture:
	node --test web/tests/profile.test.mjs web/tests/e2e.test.mjs
	PYTHONPATH=src python3 -m unittest discover -s web/tests -p 'test_*.py' -v

ui-fixture-evidence:
	ATLAS_UPDATE_EVIDENCE=1 node --test web/tests/e2e.test.mjs

web-demo:
	node web/mock-server.mjs

test: lint typecheck unit contract integration e2e ui-fixture
	find config contracts fixtures tasks -name '*.json' -type f -exec python3 -m json.tool {} \; >/dev/null

runtime-health:
	./scripts/runtime-health
