.PHONY: doctor test runtime-health

doctor:
	./scripts/atlas doctor

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v
	python3 -m json.tool config/risk-policy.json >/dev/null
	python3 -m json.tool config/runtimes.json >/dev/null
	python3 -m json.tool contracts/atlas-v1.schema.json >/dev/null
	python3 -m json.tool tasks/dag.json >/dev/null

runtime-health:
	./scripts/runtime-health

