"""`keel connect` says which Keel it is talking to, in its first line (spec
`004-shipped-runtime` FR-010; design §6.3, §5.3's startup line).

The skill that launches this process carries no address of its own and is forbidden to invent one
(X-5): every reply it gives ends with a clause naming the Keel, and this line -- into the log the
skill is already tailing for `KEEL_USER_CODE=` -- is where that clause comes from when the runtime
was started rather than merely queried.

The connect below is pointed at a closed port, so it prints its line and then fails on the network,
which is exactly what makes the assertion cheap: the line must come *first*, before anything is
attempted.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_RUNTIME_DIR = Path(__file__).resolve().parents[1]


def _run_connect(home: Path, **env_overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith("KEEL_")}
    env.update(env_overrides)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "keel_runtime",
            "connect",
            "--home",
            str(home),
            "--executor",
            "stub",
            "--no-browser",
        ],
        cwd=str(_RUNTIME_DIR),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


class ConnectStartupLineTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_first_line_names_the_environment_and_the_base_url(self):
        result = _run_connect(self.home, KEEL_BASE_URL="http://127.0.0.1:1")
        lines = result.stdout.splitlines()
        self.assertTrue(lines, msg=f"connect printed nothing; stderr: {result.stderr}")
        self.assertEqual(
            lines[0],
            "KEEL_ENVIRONMENT=127.0.0.1:1 base_url=http://127.0.0.1:1",
        )

    def test_the_line_is_printed_before_anything_is_attempted(self):
        """The port is closed, so this run fails -- and still says which Keel it failed against."""
        result = _run_connect(self.home, KEEL_BASE_URL="http://127.0.0.1:1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("KEEL_ENVIRONMENT="))

    def test_no_base_url_anywhere_reaches_the_cloud_default(self):
        """`CLOUD_BASE_URL` is a real address since design §13 step 8, so `--home` alone, with no
        `config.json` and no `KEEL_BASE_URL`, now resolves to it rather than exiting. The constant
        is pinned here to a closed port rather than the real cloud address -- same as the two
        tests above -- so this stays a hermetic, fast, deterministic failure rather than a real
        network call to production; `tests/test_home_derivation.py` and `tests/test_config.py`
        prove the real value resolves the same way, without a subprocess.
        """
        script = (
            "import sys\n"
            "from keel_runtime import config as config_module\n"
            "config_module.CLOUD_BASE_URL = 'http://127.0.0.1:1'\n"
            "from keel_runtime.cli import main\n"
            "sys.exit(main(['connect', '--home', sys.argv[1], '--executor', 'stub', "
            "'--no-browser']))\n"
        )
        env = {k: v for k, v in os.environ.items() if not k.startswith("KEEL_")}
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.home)],
            cwd=str(_RUNTIME_DIR),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        lines = result.stdout.splitlines()
        self.assertTrue(lines, msg=f"connect printed nothing; stderr: {result.stderr}")
        self.assertEqual(
            lines[0],
            "KEEL_ENVIRONMENT=cloud base_url=http://127.0.0.1:1",
        )
        self.assertNotEqual(result.returncode, 0)

    def test_the_one_line_remedy_survives_for_whenever_the_cloud_default_is_unset(self):
        """The exit-with-remedy path (design §13 step 1) is unreachable through a real subprocess
        now that `CLOUD_BASE_URL` has a value -- it is exercised the same way the in-process tests
        exercise it, by clearing the constant, but still through a real subprocess so the message
        text stays proven end to end.
        """
        script = (
            "import sys\n"
            "from keel_runtime import config as config_module\n"
            "config_module.CLOUD_BASE_URL = ''\n"
            "from keel_runtime.cli import main\n"
            "sys.exit(main(['connect', '--home', sys.argv[1], '--executor', 'stub', "
            "'--no-browser']))\n"
        )
        env = {k: v for k, v in os.environ.items() if not k.startswith("KEEL_")}
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.home)],
            cwd=str(_RUNTIME_DIR),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no base URL configured", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
