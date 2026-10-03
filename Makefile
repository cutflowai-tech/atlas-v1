.PHONY: intelligence-v2-review demo ui-v15 demo-showcase doctor lint typecheck unit contract integration e2e runtime contract-runtime normalization identity monday-probe video-type cycles-metrics status-sources quality intelligence-v15 intelligence-v2 round4-analysis contract-v13 contract-v15 contract-v14-compat profile-publication-v15 contract-v15-release deadline-v12 profile dashboard status-ui ingest sync-config monday-client ingest-runs sync-run publish lock i18n ui-v15 redesign reasoning sync-status scheduled-run alerts retention production-container production-container-docker production-deploy json test runtime-health

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

intelligence-v15:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_intelligence_v15.py' -v

intelligence-v2:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_investigation_*.py' -v

# Intelligence V2 review page on the synthetic showcase data (review mode: every finding including weak ones; never published).
intelligence-v2-review:
	mkdir -p out/intelligence-v2-showcase
	PYTHONPATH=src python3 -c 'import json; from atlas_commander.demo import showcase_extract; print(json.dumps(showcase_extract()))' > out/intelligence-v2-showcase/extract.json
	PYTHONPATH=src python3 -m atlas_commander.investigation out/intelligence-v2-showcase/extract.json out/intelligence-v2-showcase --mode review --generated-at 2026-09-28T00:00:00Z

round4-analysis:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_round4_distribution_analysis.py' -v

contract-v13:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_contract_v13.py' -v

contract-v15:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_contract_v15.py' -v

contract-v14-compat:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_contract_v14_compat.py' -v

profile-publication-v15:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_profile_publication_v15.py' -v

contract-v15-release:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_contract_v15_release.py' -v

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

ui-v15:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_ui_*.py' -v

# Reasoning V3 foundation (REV/01-06): boundary, contracts, state, case identity, change gate, provider gateway.
# Database tests run against ATLAS_REASONING_TEST_DATABASE_URL (a disposable PostgreSQL database) and are skipped without it.
reasoning:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_reasoning_*.py' -v

# Redesign (atlas-redesign-handoff): snapshot smoke test, verdict engine and judgment-first UI
redesign:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_redesign*.py' -v

sync-status:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_sync_status.py' -v

scheduled-run:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_scheduled_run.py' -v

alerts:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_alerts.py' -v

retention:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_retention.py' -v

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

test: lint typecheck unit contract integration e2e runtime normalization identity monday-probe video-type cycles-metrics status-sources quality intelligence-v15 intelligence-v2 round4-analysis contract-v13 contract-v15 contract-v14-compat profile-publication-v15 contract-v15-release deadline-v12 profile dashboard status-ui ingest sync-config monday-client ingest-runs sync-run publish lock i18n ui-v15 redesign reasoning sync-status scheduled-run alerts retention production-container production-deploy json

runtime-health:
	./scripts/runtime-health

# Local dashboard on synthetic Monday-shaped data (no token, no network): http://127.0.0.1:$(DEMO_PORT)
DEMO_PORT ?= 8000
demo:
	PYTHONPATH=src python3 -m atlas_commander.demo serve --out out/demo --port $(DEMO_PORT)

# Richer synthetic contract 1.5.0 team (varied Overall Status, speed, deadline, labels, revisions, active work)
demo-showcase:
	PYTHONPATH=src python3 -m atlas_commander.demo serve --showcase --out out/showcase --port $(DEMO_PORT)
