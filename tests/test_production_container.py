"""Task 9 production container/static-serving assets and optional Docker integration."""

import json
import os
import shutil
import subprocess
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/production"
RUN_DOCKER = os.environ.get("ATLAS_RUN_DOCKER_TESTS") == "1" and shutil.which("docker") is not None


class ProductionAssetTests(unittest.TestCase):
    def text(self, name):
        return (DEPLOY / name).read_text()

    def test_assets_are_isolated_from_user_owned_root_docker_files(self):
        expected = {"Dockerfile.app", "Dockerfile.app.dockerignore", "Dockerfile.nginx",
                    "Dockerfile.nginx.dockerignore", "nginx.conf", "compose.yaml",
                    "runtime-requirements.txt", "NOTES.md"}
        self.assertEqual({path.name for path in DEPLOY.iterdir() if path.is_file()}, expected)

    def test_app_is_pinned_python_312_unprivileged_and_safe_by_default(self):
        dockerfile = self.text("Dockerfile.app")
        self.assertRegex(dockerfile.splitlines()[0], r"^FROM python:3\.12\.12-slim-bookworm@sha256:[0-9a-f]{64}$")
        self.assertIn("USER ${ATLAS_UID}:${ATLAS_GID}", dockerfile)
        self.assertIn('ENTRYPOINT ["python", "-m", "atlas_sync"]', dockerfile)
        self.assertIn('CMD ["--help"]', dockerfile)
        self.assertNotRegex(dockerfile, r"requirements-dev|COPY \. |scheduled-run|MONDAY_API_TOKEN=")
        self.assertIn("chmod -R a-w /opt/waset-atlas", dockerfile)

    def test_dockerfile_specific_contexts_exclude_secrets_tests_fixtures_and_raw(self):
        app = self.text("Dockerfile.app.dockerignore")
        web = self.text("Dockerfile.nginx.dockerignore")
        self.assertTrue(app.startswith("**\n"))
        self.assertTrue(web.startswith("**\n"))
        for forbidden in ("!tests", "!fixtures", "!.git", "!.env", "!raw", "!requirements-dev"):
            self.assertNotIn(forbidden, app)
            self.assertNotIn(forbidden, web)
        self.assertIn("!src/**", app)
        self.assertNotIn("!src", web)

    def test_nginx_only_exposes_current_english_and_arabic(self):
        config = self.text("nginx.conf")
        self.assertIn("root /var/lib/waset-atlas/published/current;", config)
        self.assertIn("location /en/", config)
        self.assertIn("location /ar/", config)
        self.assertIn("location / {\n        return 404;", config)
        self.assertNotRegex(config, r"proxy_pass|alias|autoindex on")

    def test_compose_has_persistent_shared_volume_and_no_automatic_sync(self):
        compose = self.text("compose.yaml")
        self.assertIn("atlas-data:/var/lib/waset-atlas:ro", compose)
        self.assertIn("atlas-data:/var/lib/waset-atlas", compose)
        self.assertIn('profiles: ["operations"]', compose)
        self.assertIn('command: ["status", "--json"]', compose)
        self.assertNotRegex(compose, r"command:.*(?:scheduled-run|run-once)|down -v|volume rm|rm -rf")
        self.assertIn("read_only: true", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn("external: true", compose)


@unittest.skipUnless(RUN_DOCKER, "set ATLAS_RUN_DOCKER_TESTS=1 with a Docker daemon for image/runtime tests")
class DockerRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        suffix = uuid.uuid4().hex[:10]
        cls.app_image = f"waset-atlas-app-test:{suffix}"
        cls.web_image = f"waset-atlas-web-test:{suffix}"
        cls.volume = f"waset-atlas-data-test-{suffix}"
        cls.container = f"waset-atlas-web-test-{suffix}"
        subprocess.run(["docker", "build", "--pull=false", "-f", str(DEPLOY / "Dockerfile.app"),
                        "-t", cls.app_image, str(ROOT)], check=True, capture_output=True, text=True, timeout=300)
        subprocess.run(["docker", "build", "--pull=false", "-f", str(DEPLOY / "Dockerfile.nginx"),
                        "-t", cls.web_image, str(ROOT)], check=True, capture_output=True, text=True, timeout=300)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "rm", "-f", cls.container], capture_output=True, check=False)
        subprocess.run(["docker", "volume", "rm", "-f", cls.volume], capture_output=True, check=False)
        subprocess.run(["docker", "image", "rm", "-f", cls.app_image, cls.web_image], capture_output=True, check=False)

    def docker(self, *args, check=True):
        return subprocess.run(["docker", *args], check=check, capture_output=True, text=True, timeout=120)

    def test_app_image_identity_contents_permissions_and_zero_action_startup(self):
        inspected = json.loads(self.docker("image", "inspect", self.app_image).stdout)[0]
        config = inspected["Config"]
        self.assertEqual(config["User"], "10001:10001")
        self.assertEqual(config["Entrypoint"], ["python", "-m", "atlas_sync"])
        self.assertEqual(config["Cmd"], ["--help"])
        self.assertFalse(any(value.startswith("MONDAY_API_TOKEN=") for value in config["Env"]))
        started = self.docker("run", "--rm", "--network", "none", "--read-only", self.app_image)
        self.assertIn("scheduled-run", started.stdout)
        listing = self.docker("run", "--rm", "--network", "none", "--read-only", "--entrypoint", "/bin/sh",
                              self.app_image, "-c", "find /opt/waset-atlas -maxdepth 2 -type d -print; test ! -w /opt/waset-atlas/src").stdout
        for forbidden in ("/tests", "/fixtures", "/.git", "/raw"):
            self.assertNotIn(forbidden, listing)

    def _seed_volume(self):
        script = ("set -eu; mkdir -p /var/lib/waset-atlas/builds/build-one/site/en "
                  "/var/lib/waset-atlas/builds/build-one/site/ar /var/lib/waset-atlas/published; "
                  "printf EN-CURRENT > /var/lib/waset-atlas/builds/build-one/site/en/dashboard.html; "
                  "printf AR-CURRENT > /var/lib/waset-atlas/builds/build-one/site/ar/dashboard.html; "
                  "ln -s ../builds/build-one/site /var/lib/waset-atlas/published/current")
        self.docker("run", "--rm", "--network", "none", "-v", f"{self.volume}:/var/lib/waset-atlas",
                    "--entrypoint", "/bin/sh", self.app_image, "-c", script)

    def _wget(self, path, check=True):
        return self.docker("exec", self.container, "wget", "-q", "-O", "-", f"http://127.0.0.1:8080{path}", check=check)

    def test_shared_volume_current_locales_and_restart_persistence(self):
        self._seed_volume()
        self.docker("run", "-d", "--name", self.container, "--read-only", "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:size=16m,mode=1777",
                    "-v", f"{self.volume}:/var/lib/waset-atlas:ro", self.web_image)
        for _ in range(30):
            response = self._wget("/en/dashboard.html", check=False)
            if response.returncode == 0:
                break
            time.sleep(0.1)
        self.assertEqual(self._wget("/en/dashboard.html").stdout, "EN-CURRENT")
        self.assertEqual(self._wget("/ar/dashboard.html").stdout, "AR-CURRENT")
        self.assertNotEqual(self._wget("/builds/build-one/site/en/dashboard.html", check=False).returncode, 0)
        self.docker("restart", self.container)
        for _ in range(30):
            response = self._wget("/ar/dashboard.html", check=False)
            if response.returncode == 0:
                break
            time.sleep(0.1)
        self.assertEqual(self._wget("/ar/dashboard.html").stdout, "AR-CURRENT")
        link = self.docker("run", "--rm", "-v", f"{self.volume}:/var/lib/waset-atlas:ro", "--entrypoint", "/bin/sh",
                           self.app_image, "-c", "readlink /var/lib/waset-atlas/published/current").stdout.strip()
        self.assertEqual(link, "../builds/build-one/site")
        scheduled = self.docker("run", "--rm", "-v", f"{self.volume}:/var/lib/waset-atlas:ro", "--entrypoint", "/bin/sh",
                                self.app_image, "-c", "test ! -e /var/lib/waset-atlas/locks/scheduled-cycles")
        self.assertEqual(scheduled.returncode, 0)


if __name__ == "__main__":
    unittest.main()
