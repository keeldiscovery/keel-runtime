"""The shipped configuration is the one without the extras (invariants R-1 and R-2; spec
`004-shipped-runtime` FR-003; design §4.4, decision 4).

`keyring` and `jsonschema` are declared under `[project.optional-dependencies]` and guarded by
`try: import`. Installing the package installs neither, so the *shipped* behaviour -- a `0600`
credential file and the stdlib subset validator -- is what every founder runs, on every machine, by
default. That is a decision, not an accident, and it needs a test that holds even on a machine where
somebody has installed both.

So each test here runs a **subprocess** whose import hook raises `ImportError` for those two names
before `keel_runtime` is imported at all. It is the same thing the CI matrix does by simply not
installing them (FR-002), asserted from inside the repository so a developer with a full toolbox
cannot lose it.
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_RUNTIME_DIR = Path(__file__).resolve().parents[1]

_BLOCKER = textwrap.dedent(
    '''
    import sys

    _BLOCKED = ("keyring", "jsonschema")


    class _Blocked:
        """Refuses the two optional accelerators the way a founder's machine does: they are
        simply not there."""

        def find_module(self, fullname, path=None):  # Python 3.9's legacy hook, still consulted
            return self if self._blocks(fullname) else None

        def find_spec(self, fullname, path=None, target=None):
            if self._blocks(fullname):
                raise ImportError("blocked by the R-2 test: " + fullname)
            return None

        @staticmethod
        def _blocks(fullname):
            return any(fullname == name or fullname.startswith(name + ".") for name in _BLOCKED)


    sys.meta_path.insert(0, _Blocked())
    for _name in list(sys.modules):
        if any(_name == b or _name.startswith(b + ".") for b in _BLOCKED):
            del sys.modules[_name]
    '''
)


def _run_python(body: str, **env_overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith("KEEL_")}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", _BLOCKER + textwrap.dedent(body)],
        cwd=str(_RUNTIME_DIR),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


class WithoutTheOptionalAcceleratorsTest(unittest.TestCase):
    def test_every_module_imports(self):
        """R-1: the runtime imports and runs with no third-party package installed."""
        result = _run_python(
            """
            import importlib, pkgutil
            import keel_runtime

            names = ["keel_runtime"]
            for module in pkgutil.walk_packages(keel_runtime.__path__, "keel_runtime."):
                names.append(module.name)
            for name in names:
                importlib.import_module(name)
            print(len(names))
            """
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertGreaterEqual(int(result.stdout.strip()), 12)

    def test_the_two_names_really_are_unimportable_in_that_subprocess(self):
        """The blocker itself, asserted -- otherwise a green run here would prove nothing."""
        result = _run_python(
            """
            for name in ("keyring", "jsonschema"):
                try:
                    __import__(name)
                except ImportError:
                    continue
                raise SystemExit("import of " + name + " succeeded; the blocker is broken")
            print("blocked")
            """
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "blocked")

    def test_the_stdlib_subset_validator_is_the_one_that_runs(self):
        """R-2, and the load-bearing half of design §4.4: with `jsonschema` absent, the runtime's
        own validator is the only thing between a model's prose and the poller.
        """
        result = _run_python(
            """
            from keel_runtime import response_validator

            assert response_validator._JSONSCHEMA_AVAILABLE is False, "jsonschema leaked in"

            contract = {
                "allowed_outcomes": ["COMPLETED"],
                "completed_result_schema": {
                    "type": "object",
                    "required": ["statement"],
                    "properties": {"statement": {"type": "string", "maxLength": 20}},
                    "additionalProperties": False,
                },
            }
            response_validator.validate_response(
                {"outcome": "COMPLETED", "result": {"statement": "short enough"}}, contract
            )
            for bad in (
                {"outcome": "COMPLETED", "result": {"statement": "x" * 21}},
                {"outcome": "COMPLETED", "result": {"statement": "ok", "extra": 1}},
                {"outcome": "COMPLETED", "result": {}},
                {"outcome": "NOPE"},
            ):
                try:
                    response_validator.validate_response(bad, contract)
                except response_validator.InvalidResponse:
                    continue
                raise SystemExit("the subset validator accepted " + repr(bad))
            print("validated")
            """
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "validated")

    def test_the_credential_store_falls_back_to_a_0600_file(self):
        """R-2's other half: no `keyring`, so the credential is a `0600` JSON file under the
        home -- the derived home, since spec 004.
        """
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_python(
                """
                import json, os, stat, sys
                from pathlib import Path

                from keel_runtime import credential_store

                assert credential_store._KEYRING_AVAILABLE is False, "keyring leaked in"

                home = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ["KEEL_TEST_HOME"])
                store = credential_store.CredentialStore(home, backend="auto")
                store.save(
                    credential_store.Credential(
                        access_token="t", refresh_token="r", expires_at=1.0, scope=["a"]
                    )
                )
                path = home / "credentials.json"
                mode = stat.S_IMODE(path.stat().st_mode)
                print(json.dumps({"mode": oct(mode), "token": store.load().access_token}))
                """,
                KEEL_TEST_HOME=tmp,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout.strip())
            self.assertEqual(payload["token"], "t")
            if os.name != "nt":  # POSIX permissions only
                self.assertEqual(payload["mode"], "0o600")

    def test_status_answers_and_exits_zero(self):
        """R-4 under R-2: the one command a skill runs first still works with nothing installed."""
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_python(
                """
                import os, sys
                from keel_runtime.cli import main

                raise SystemExit(main(["status", "--home", os.environ["KEEL_TEST_HOME"]]))
                """,
                KEEL_TEST_HOME=tmp,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout.strip())
            self.assertIs(payload["running"], False)


if __name__ == "__main__":
    unittest.main()
