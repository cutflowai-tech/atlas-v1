"""Task 9 production container/static-serving assets and optional Docker integration."""

import json
import os
import shutil
import subprocess
import tempfile
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
        self.assertTrue(expected <= {path.name for path in DEPLOY.iterdir() if path.is_file()})

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
        self.assertIn("location = / {\n        try_files /index.html =404;", config)
        self.assertIn("location /en/", config)
        self.assertIn("location /ar/", config)
        self.assertIn("location / {\n        return 404;", config)
        self.assertNotRegex(config, r"proxy_pass|alias|autoindex on")

    def test_compose_has_persistent_bind_mount_and_no_automatic_sync(self):
        compose = self.text("compose.yaml")
        self.assertEqual(compose.count("source: ${ATLAS_HOST_DATA_DIR:-/var/lib/waset-atlas}"), 2)
        self.assertEqual(compose.count("target: /var/lib/waset-atlas"), 2)
        self.assertIn("atlas-runtime:", compose)
        self.assertIn("source: ${ATLAS_TOKEN_FILE:-/etc/waset-atlas/secrets/monday_api_token}", compose)
        self.assertIn("target: /run/secrets/monday_api_token", compose)
        self.assertIn('user: "${ATLAS_UID:-10001}:${ATLAS_GID:-10001}"', compose)
        self.assertIn('group_add:\n      - "${ATLAS_GID:-10001}"', compose)
        self.assertIn('profiles: ["operations"]', compose)
        self.assertIn('command: ["status", "--json"]', compose)
        self.assertNotRegex(compose, r"command:.*(?:scheduled-run|run-once)|down -v|volume rm|rm -rf")
        self.assertIn("read_only: true", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertNotIn("MONDAY_API_TOKEN:", compose)


@unittest.skipUnless(RUN_DOCKER, "set ATLAS_RUN_DOCKER_TESTS=1 with a Docker daemon for image/runtime tests")
class DockerRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        suffix = uuid.uuid4().hex[:10]
        cls.sentinel = f"TASK9_TEST_ONLY_SECRET_{uuid.uuid4().hex}"
        cls.sentinel_path = ROOT / ".task9-build-secret-sentinel"
        cls.app_image = f"waset-atlas-app-test:{suffix}"
        cls.web_image = f"waset-atlas-web-test:{suffix}"
        cls.data_dir = Path(tempfile.mkdtemp(prefix="waset-atlas-data-test-"))
        cls.data_dir.chmod(0o777)
        cls.container = f"waset-atlas-web-test-{suffix}"
        cls.sentinel_path.write_text(cls.sentinel, encoding="utf-8")
        try:
            subprocess.run(["docker", "build", "--pull=false", "-f", str(DEPLOY / "Dockerfile.app"),
                            "-t", cls.app_image, str(ROOT)], check=True, capture_output=True, text=True, timeout=300)
            subprocess.run(["docker", "build", "--pull=false", "-f", str(DEPLOY / "Dockerfile.nginx"),
                            "-t", cls.web_image, str(ROOT)], check=True, capture_output=True, text=True, timeout=300)
        finally:
            cls.sentinel_path.unlink(missing_ok=True)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "rm", "-f", cls.container], capture_output=True, check=False)
        subprocess.run(["docker", "image", "rm", "-f", cls.app_image, cls.web_image], capture_output=True, check=False)
        shutil.rmtree(cls.data_dir, ignore_errors=True)
        cls.sentinel_path.unlink(missing_ok=True)

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
        combined = json.dumps(inspected) + self.docker("history", "--no-trunc", self.app_image).stdout + started.stdout + started.stderr
        self.assertNotIn(self.sentinel, combined)
        listing = self.docker("run", "--rm", "--network", "none", "--read-only", "--entrypoint", "/bin/sh",
                              self.app_image, "-c", "find /opt/waset-atlas -maxdepth 2 -type d -print; "
                              "test ! -w /opt/waset-atlas/src; "
                              f"! grep -R -F {self.sentinel!r} /opt/waset-atlas /etc 2>/dev/null").stdout
        for forbidden in ("/tests", "/fixtures", "/.git", "/raw"):
            self.assertNotIn(forbidden, listing)

    def test_compose_uses_external_images_environment_and_host_bind(self):
        env_path = self.data_dir.parent / f"atlas-compose-{uuid.uuid4().hex}.env"
        token_path = self.data_dir.parent / f"atlas-token-{uuid.uuid4().hex}"
        token_path.write_text("test-only-not-a-real-token\n", encoding="utf-8")
        env_path.write_text(
            f"ATLAS_APP_IMAGE={self.app_image}\nATLAS_WEB_IMAGE={self.web_image}\n"
            f"ATLAS_HOST_DATA_DIR={self.data_dir}\nATLAS_TOKEN_FILE={token_path}\n"
            "ATLAS_UID=10001\nATLAS_GID=10001\nATLAS_HTTP_BIND=127.0.0.1\nATLAS_HTTP_PORT=18000\n",
            encoding="utf-8",
        )
        try:
            rendered = self.docker(
                "compose", "--env-file", str(env_path), "--project-directory", str(ROOT),
                "-f", str(DEPLOY / "compose.yaml"), "--profile", "operations", "config", "--format", "json",
            )
            config = json.loads(rendered.stdout)
            self.assertEqual(config["services"]["atlas-web"]["image"], self.web_image)
            runtime = config["services"]["atlas-runtime"]
            self.assertEqual((runtime["image"], runtime["user"]), (self.app_image, "10001:10001"))
            self.assertEqual(runtime["volumes"][0]["source"], str(self.data_dir))
            self.assertEqual(runtime["volumes"][1]["source"], str(token_path))
            self.assertNotIn("build", config["services"]["atlas-web"])
            self.assertNotIn("build", runtime)
        finally:
            env_path.unlink(missing_ok=True)
            token_path.unlink(missing_ok=True)

    def _seed_data(self):
        script = ("set -eu; mkdir -p /var/lib/waset-atlas/builds/build-one/site/en "
                  "/var/lib/waset-atlas/builds/build-one/site/ar /var/lib/waset-atlas/published; "
                  "printf '<meta http-equiv=refresh content=\"0;url=en/\">EN-DEFAULT' "
                  "> /var/lib/waset-atlas/builds/build-one/site/index.html; "
                  "printf EN-CURRENT > /var/lib/waset-atlas/builds/build-one/site/en/dashboard.html; "
                  "printf AR-CURRENT > /var/lib/waset-atlas/builds/build-one/site/ar/dashboard.html; "
                  "ln -s ../builds/build-one/site /var/lib/waset-atlas/published/current")
        self.docker("run", "--rm", "--network", "none", "-v", f"{self.data_dir}:/var/lib/waset-atlas",
                    "--entrypoint", "/bin/sh", self.app_image, "-c", script)

    def _wget(self, path, check=True):
        return self.docker("exec", self.container, "wget", "-q", "-O", "-", f"http://127.0.0.1:8080{path}", check=check)

    def test_shared_volume_current_locales_and_restart_persistence(self):
        self._seed_data()
        self.docker("run", "-d", "--name", self.container, "--read-only", "--cap-drop", "ALL", "--group-add", "10001",
                    "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:size=16m,mode=1777",
                    "-v", f"{self.data_dir}:/var/lib/waset-atlas:ro", self.web_image)
        for _ in range(30):
            response = self._wget("/en/dashboard.html", check=False)
            if response.returncode == 0:
                break
            time.sleep(0.1)
        self.assertEqual(self._wget("/en/dashboard.html").stdout, "EN-CURRENT")
        self.assertEqual(self._wget("/ar/dashboard.html").stdout, "AR-CURRENT")
        self.assertIn("EN-DEFAULT", self._wget("/").stdout)
        self.assertNotEqual(self._wget("/builds/build-one/site/en/dashboard.html", check=False).returncode, 0)
        self.docker("rm", "-f", self.container)
        self.docker("run", "-d", "--name", self.container, "--read-only", "--cap-drop", "ALL", "--group-add", "10001",
                    "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:size=16m,mode=1777",
                    "-v", f"{self.data_dir}:/var/lib/waset-atlas:ro", self.web_image)
        for _ in range(30):
            response = self._wget("/ar/dashboard.html", check=False)
            if response.returncode == 0:
                break
            time.sleep(0.1)
        self.assertEqual(self._wget("/ar/dashboard.html").stdout, "AR-CURRENT")
        link = self.docker("run", "--rm", "-v", f"{self.data_dir}:/var/lib/waset-atlas:ro", "--entrypoint", "/bin/sh",
                           self.app_image, "-c", "readlink /var/lib/waset-atlas/published/current").stdout.strip()
        self.assertEqual(link, "../builds/build-one/site")
        scheduled = self.docker("run", "--rm", "-v", f"{self.data_dir}:/var/lib/waset-atlas:ro", "--entrypoint", "/bin/sh",
                                self.app_image, "-c", "test ! -e /var/lib/waset-atlas/locks/scheduled-cycles")
        self.assertEqual(scheduled.returncode, 0)
        exported = self.docker("run", "--rm", "-v", f"{self.data_dir}:/var/lib/waset-atlas:ro", "--entrypoint", "/bin/sh",
                               self.app_image, "-c", "grep -R -F TASK9_TEST_ONLY_SECRET /var/lib/waset-atlas 2>/dev/null", check=False)
        self.assertNotEqual(exported.returncode, 0)
        self.assertNotIn(self.sentinel, exported.stdout + exported.stderr)


if __name__ == "__main__":
    unittest.main()
