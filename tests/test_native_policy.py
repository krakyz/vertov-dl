import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "native_policy", Path(__file__).parents[1] / "scripts" / "check-native.py"
)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


@pytest.mark.parametrize(
    "version,accepted", [("7:7.1.5-0+deb13u1", True), ("7:5.1.9-0+deb12u1", False)]
)
def test_native_security_gate_checks_every_installed_package(monkeypatch, version, accepted):
    monkeypatch.setattr(policy.Path, "read_text", lambda *_: "ID=debian\nVERSION_CODENAME=trixie\n")
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        if args[0] == "dpkg-query":
            return SimpleNamespace(stdout=version, returncode=0)
        return SimpleNamespace(returncode=0 if accepted else 1)

    monkeypatch.setattr(policy.subprocess, "run", run)
    if accepted:
        result = policy.audit_native()
        assert set(result["packages"]) == set(policy.PACKAGES)
        assert len(commands) == len(policy.PACKAGES) * 2
        assert result["security_check"]["cve"] == "CVE-2026-8461"
    else:
        with pytest.raises(RuntimeError, match="CVE-2026-8461"):
            policy.audit_native()


def test_wrong_suite_is_not_accepted_by_major_version(monkeypatch):
    monkeypatch.setattr(
        policy.Path, "read_text", lambda *_: "ID=debian\nVERSION_CODENAME=bookworm\n"
    )
    with pytest.raises(RuntimeError, match="trixie"):
        policy.audit_native()
