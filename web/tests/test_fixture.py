import json
import unittest
from pathlib import Path
from atlas_commander.contracts import assert_valid


class FixtureContractTests(unittest.TestCase):
    def test_populated_demo_contract(self):
        profile = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/editor-profile.json').read_text())
        assert_valid(profile, 'editor-profile.schema.json')
        for kind, metrics in profile['metrics'].items():
            for metric in metrics:
                assert_valid(metric, f'{kind}-metric.schema.json')
        for cycle in profile['work_cycles']:
            assert_valid(cycle, 'work-cycle.schema.json')

    def test_mock_api_handler_without_starting_server(self):
        import importlib.util
        from io import BytesIO
        spec = importlib.util.spec_from_file_location('fixture_demo', Path(__file__).resolve().parents[1] / 'demo.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        handler = module.Handler.__new__(module.Handler)
        handler.path = '/api/editors/editor-42'
        handler.wfile = BytesIO()
        statuses = []
        handler.send_response = statuses.append
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.send_error = lambda status, message: statuses.append(status)
        handler.do_GET()
        self.assertEqual(statuses, [200])
        self.assertEqual(json.loads(handler.wfile.getvalue())['editor']['editor_id'], 'editor-42')
        handler.path = '/api/editors/unknown'
        handler.do_GET()
        self.assertEqual(statuses, [200, 404])
