.PHONY: doctor lint typecheck unit contract integration e2e runtime contract-runtime normalization identity monday-probe video-type cycles-metrics json test runtime-health

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

runtime:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_contract_config.py' -v

normalization:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_normalization.py' -v

identity:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_identity.py' -v

monday-probe:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_monday_probe.py' -v

video-type:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_video_type.py' -v

cycles-metrics:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_cycles_metrics.py' -v

json:
	find config contracts fixtures tasks -name '*.json' -type f -exec python3 -m json.tool {} \; >/dev/null

test: lint typecheck unit contract integration e2e runtime normalization identity monday-probe video-type cycles-metrics json

runtime-health:
	./scripts/runtime-health
