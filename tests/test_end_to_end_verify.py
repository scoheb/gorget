"""End-to-end: fetch -> verify through the real PipelineRunner. GPG operations
are real (no mocking) -- self-contained, no network needed. HTTP downloads are
mocked since there's no real server to fetch from.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from gorget.cli import resolve_pipeline_spec
from gorget.context import build_run_context
from gorget.exceptions import GorgetPolicyViolation
from gorget.pipeline.runner import PipelineRunner

requires_gpg = pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg not installed")

TARBALL_CONTENT = b"tarball contents for end-to-end verify test"

PIPELINE_YAML_WITH_GPG = """
fetch:
  - type: url
    url: "https://example.com/foo-1.2.3.tar.gz"
  - type: url
    url: "https://example.com/foo-1.2.3.tar.gz.asc"
verify:
  - type: gpg-signature
    target: "foo-1.2.3.tar.gz"
    signature: "foo-1.2.3.tar.gz.asc"
    keyring: "example-project.gpg"
"""

PIPELINE_YAML_FETCH_ONLY = """
fetch:
  - type: url
    url: "https://example.com/foo-1.2.3.tar.gz"
"""


def make_ctx(tmp_path, pipeline_yaml, gpg_keys_dir=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "foo.spec").write_text("Name: foo\nVersion: 1.2.3\nRelease: 1\n")
    pipeline_file = tmp_path / "pipeline.yaml"
    pipeline_file.write_text(pipeline_yaml)
    args = argparse.Namespace(
        pkg_version="1.2.3",
        old_version=None,
        dry_run=False,
        package_dir=str(tmp_path),
        pipeline_file=str(pipeline_file),
        gpg_keys_dir=str(gpg_keys_dir or (tmp_path / "gpg-keys")),
        output_dir=str(tmp_path / "output"),
        upstream_repo=None,
    )
    return build_run_context(args)


def _run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result


def _make_signed_keyring_and_signature(tmp_path):
    """Real gpg keygen + sign, returns (keyring_bytes, signature_bytes)."""
    gen_home = tmp_path / "gen-home"
    gen_home.mkdir(mode=0o700, parents=True)
    _run(
        [
            "gpg", "--homedir", str(gen_home), "--batch", "--passphrase", "",
            "--quick-generate-key", "Test <test@example.com>", "default", "default", "never",
        ]
    )
    keyring = subprocess.run(
        ["gpg", "--homedir", str(gen_home), "--batch", "--export", "test@example.com"],
        capture_output=True, check=True,
    ).stdout

    target_path = tmp_path / "signing-target.tar.gz"
    target_path.write_bytes(TARBALL_CONTENT)
    sig_path = tmp_path / "signing-target.tar.gz.asc"
    _run(
        [
            "gpg", "--homedir", str(gen_home), "--batch", "--local-user", "test@example.com",
            "--detach-sign", "-o", str(sig_path), str(target_path),
        ]
    )
    return keyring, sig_path.read_bytes()


@pytest.mark.integration
@requires_gpg
def test_fetch_then_gpg_signature_succeeds_end_to_end(tmp_path, mocker):
    keyring_bytes, signature_bytes = _make_signed_keyring_and_signature(tmp_path / "_setup")

    gpg_keys_dir = tmp_path / "gpg-keys"
    gpg_keys_dir.mkdir()
    (gpg_keys_dir / "example-project.gpg").write_bytes(keyring_bytes)

    def fake_download(url, dest):
        if url.endswith(".asc"):
            dest.write_bytes(signature_bytes)
        else:
            dest.write_bytes(TARBALL_CONTENT)

    mocker.patch("gorget.fetch.url.download_to", side_effect=fake_download)

    ctx = make_ctx(tmp_path / "pkg", PIPELINE_YAML_WITH_GPG, gpg_keys_dir=gpg_keys_dir)
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["fetch"] == "success"
    assert stage_status["verify"] == "success"
    assert stage_status["emit"] == "success"

    verify_stage = next(s for s in report.stages if s.name == "verify")
    assert verify_stage.details == [
        {"type": "gpg-signature", "target": "foo-1.2.3.tar.gz", "status": "passed", "reason": None}
    ]

    report_json = json.loads((Path(ctx.output_dir) / "report.json").read_text())
    verify_json = next(s for s in report_json["stages"] if s["name"] == "verify")
    assert verify_json["details"][0]["status"] == "passed"


def test_fetch_then_republication_mismatch_fails_closed_then_accepted_checksums_cures_it(
    tmp_path, mocker
):
    mocker.patch(
        "gorget.fetch.url.download_to",
        side_effect=lambda url, dest: dest.write_bytes(TARBALL_CONTENT),
    )
    new_digest = hashlib.sha512(TARBALL_CONTENT).hexdigest()

    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "sources").write_text("SHA512 (foo-1.2.3.tar.gz) = " + "a" * 128 + "\n")

    ctx = make_ctx(package_dir, PIPELINE_YAML_FETCH_ONLY)
    spec = resolve_pipeline_spec(ctx)
    with pytest.raises(GorgetPolicyViolation, match="foo-1.2.3.tar.gz"):
        PipelineRunner(ctx, spec).run()

    # Add the accepted-checksums override a human would copy from the error
    # message, and confirm the same run now succeeds.
    accepted_yaml = PIPELINE_YAML_FETCH_ONLY + (
        "accepted-checksums:\n"
        '  - file: "foo-1.2.3.tar.gz"\n'
        f'    checksum: "{new_digest}"\n'
        '    reason: "test: legitimate re-publication"\n'
    )
    ctx2 = make_ctx(package_dir, accepted_yaml)
    spec2 = resolve_pipeline_spec(ctx2)
    report = PipelineRunner(ctx2, spec2).run()

    verify_stage = next(s for s in report.stages if s.name == "verify")
    assert verify_stage.status == "success"
    assert verify_stage.details[0]["status"] == "accepted"
