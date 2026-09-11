"""`keel --version` and `keel --license` (spec `004-shipped-runtime` FR-004/FR-005).

There was no version at all before this: `__version__` was the only stamp, `git tag` was empty and
nothing printed either (design §2). A runtime that travels inside four packagings has to be able to
answer *which one are you* on a founder's machine -- §10.3's Windows bed asserts exactly this, as a
subprocess, which is how it is asserted here.

`--version` and `--license` are top-level flags over a parser whose subcommand is `required=True`:
argparse runs an optional's action as it consumes the argument, so both fire before the
missing-subcommand check. Running them as real subprocesses is the only way to prove that.
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path

import keel_runtime
from keel_runtime import cli as cli_module
from keel_runtime import config as config_module

_RUNTIME_DIR = Path(__file__).resolve().parents[1]


def _run(*argv, **env_overrides):
    import os

    env = {k: v for k, v in os.environ.items() if not k.startswith("KEEL_")}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "keel_runtime", *argv],
        cwd=str(_RUNTIME_DIR),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


class VersionFlagTest(unittest.TestCase):
    def test_version_prints_one_line_and_exits_zero_with_no_subcommand(self):
        result = _run("--version")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1, msg=repr(result.stdout))
        self.assertEqual(
            lines[0],
            f"keel-runtime {keel_runtime.__version__} (Keel Cloud https://keeldiscovery.com)",
        )

    def test_the_version_is_a_semver_looking_string(self):
        self.assertRegex(keel_runtime.__version__, r"^\d+\.\d+\.\d+")

    def test_pyproject_declares_the_same_version_as_the_package(self):
        """FR-004: the constant is the source of truth, and `pyproject.toml` mirrors it. The
        shipped runtime is never installed (design §3.2), so package metadata is not an option --
        but the two must not be allowed to drift for anyone who does install it.
        """
        pyproject = (_RUNTIME_DIR / "pyproject.toml").read_text(encoding="utf-8")
        declared = re.search(r'^version = "([^"]+)"', pyproject, flags=re.MULTILINE)
        self.assertIsNotNone(declared, msg="pyproject.toml has no top-level version")
        self.assertEqual(declared.group(1), keel_runtime.__version__)

    def test_version_names_whatever_the_constant_is_set_to(self):
        """Design §13 step 8's whole edit was the constant; this is what it prints, for any value
        the constant holds -- proven here with a value distinct from today's real one.
        """
        original = config_module.CLOUD_BASE_URL
        try:
            config_module.CLOUD_BASE_URL = "https://cloud.keel.example"
            self.assertEqual(
                cli_module.version_line(),
                f"keel-runtime {keel_runtime.__version__} (Keel Cloud https://cloud.keel.example)",
            )
        finally:
            config_module.CLOUD_BASE_URL = original

    def test_the_constant_is_set_to_the_real_keel_cloud_address(self):
        """Since design §13 step 8 (spec 034, live 2026-09-09), the constant is no longer the
        empty placeholder -- it names keel-cloud's real, deployed address.
        """
        self.assertEqual(config_module.CLOUD_BASE_URL, "https://keeldiscovery.com")
        source = (_RUNTIME_DIR / "keel_runtime" / "config.py").read_text(encoding="utf-8")
        self.assertIn('CLOUD_BASE_URL = "https://keeldiscovery.com"', source)
        self.assertIn("step 8", source)


class LicenseFlagTest(unittest.TestCase):
    def test_license_names_the_licence_and_exits_zero(self):
        result = _run("--license")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(keel_runtime.__license__, result.stdout)
        self.assertIn(keel_runtime.LICENSE_URL, result.stdout)
        self.assertIn(keel_runtime.COPYRIGHT, result.stdout)

    def test_license_states_that_nothing_third_party_is_bundled(self):
        """The claim the packaging leans on: `keel_runtime/` is copied verbatim into every tree
        (design §3.1) and carries no vendored dependency to license alongside it.
        """
        text = cli_module.license_text()
        self.assertIn("bundles no third-party code", text)
        self.assertIn("standard library", text)

    def test_neither_flag_needs_a_subcommand_and_neither_writes_to_stderr(self):
        for flag in ("--version", "--license"):
            with self.subTest(flag=flag):
                result = _run(flag)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
