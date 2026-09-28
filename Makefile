.PHONY: doctor lint typecheck unit contract integration e2e test runtime-health monday-probe

# Dedicated suites run through their own targets locally and in CI.
UNIT_TEST_FILES := $(filter-out tests/test_contracts.py tests/test_integration.py tests/test_e2e.py,$(wildcard tests/test_*.py))

doctor:
	./scripts/atlas doctor

lint:
	ruff check src tests

typecheck:
	mypy src

unit:
	@set -e; for test_file in $(UNIT_TEST_FILES); do \
		PYTHONPATH=src python3 -m unittest discover -s tests -p "$${test_file##*/}" -v; \
	done

contract:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_contracts.py' -v

integration:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_integration.py' -v

e2e:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_e2e.py' -v

monday-probe:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_monday_probe.py' -v

test: lint typecheck unit contract integration e2e monday-probe
	find config contracts fixtures tasks -name '*.json' -type f -exec python3 -m json.tool {} \; >/dev/null

runtime-health:
	./scripts/runtime-health
