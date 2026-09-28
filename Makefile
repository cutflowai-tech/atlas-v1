.PHONY: doctor lint typecheck unit contract integration e2e runtime contract-runtime normalization identity monday-probe video-type cycles-metrics status-sources quality contract-v13 deadline-v12 profile dashboard status-ui ingest sync-config monday-client ingest-runs sync-run publish lock i18n sync-status scheduled-run alerts production-container production-container-docker production-deploy json test runtime-health

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

status-sources:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_status_sources.py' -v

quality:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_quality.py' -v

contract-v13:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_contract_v13.py' -v

deadline-v12:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_deadline_v12.py' -v

profile:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_profile.py' -v

dashboard:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_dashboard.py' -v

status-ui:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_status_dashboard_ui.py' -v

sync-config:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_sync_config.py' -v

monday-client:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_monday_client.py' -v

ingest-runs:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_ingest_runs.py' -v

sync-run:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_sync_run.py' -v

publish:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_publish.py' -v

lock:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_lock.py' -v

i18n:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_i18n.py' -v

sync-status:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_sync_status.py' -v

scheduled-run:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_scheduled_run.py' -v

alerts:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_alerts.py' -v

production-container:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_production_container.py' -v

production-container-docker:
	ATLAS_RUN_DOCKER_TESTS=1 PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_production_container.py' -v

production-deploy:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_production_deploy.py' -v

ingest:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_ingest.py' -v

json:
	find config contracts fixtures tasks -name '*.json' -type f -exec python3 -m json.tool {} \; >/dev/null

test: lint typecheck unit contract integration e2e runtime normalization identity monday-probe video-type cycles-metrics status-sources quality contract-v13 deadline-v12 profile dashboard status-ui ingest sync-config monday-client ingest-runs sync-run publish lock i18n sync-status scheduled-run alerts production-container production-deploy json

runtime-health:
	./scripts/runtime-health
