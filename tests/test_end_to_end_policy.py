"""End-to-end: fetch (real git clone) -> transform (real npm install) ->
policy (real vendor-constraints check reading node_modules) through the real
PipelineRunner. No mocking -- a real, tiny, stable npm package ("ms") is
fetched from the real npm registry, matching the real-toolchain-test precedent
used elsewhere in this suite. Requires `git`/`npm` on PATH and network access.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess

import pytest

from gorget.cli import resolve_pipeline_spec
from gorget.context import build_run_context
from gorget.exceptions import GorgetPolicyViolation
from gorget.pipeline.runner import PipelineRunner

requires_git_and_npm = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("npm") is None,
    reason="git and npm required",
)

PIPELINE_YAML = """
fetch:
  - type: git
    repo: "{repo}"
    ref: "v1.0.0"
transform:
  - type: vendor
    ecosystem: npm
policy:
  vendor-constraints:
    - package: ms
      ecosystem: npm
      version: "{minimum}"
      reason: "test: pin confirmation"
"""


def _run(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result


def make_git_repo(tmp_path):
    repo_dir = tmp_path / "upstream.git"
    repo_dir.mkdir(parents=True)
    (repo_dir / "package.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0", "dependencies": {"ms": "2.0.0"}})
    )
    _run(["git", "init"], cwd=repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir)
    _run(["git", "config", "user.name", "Test"], cwd=repo_dir)
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "initial"], cwd=repo_dir)
    _run(["git", "tag", "v1.0.0"], cwd=repo_dir)
    return repo_dir


def make_ctx(package_dir, pipeline_yaml):
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "foo.spec").write_text("Name: foo\nVersion: 1.0.0\nRelease: 1\n")
    pipeline_file = package_dir / "pipeline.yaml"
    pipeline_file.write_text(pipeline_yaml)
    args = argparse.Namespace(
        pkg_version="1.0.0",
        old_version=None,
        dry_run=False,
        package_dir=str(package_dir),
        pipeline_file=str(pipeline_file),
        gpg_keys_dir=str(package_dir / "gpg-keys"),
        output_dir=str(package_dir / "output"),
        upstream_repo=None,
    )
    return build_run_context(args)


@requires_git_and_npm
@pytest.mark.integration
def test_fetch_then_vendor_then_policy_constraint_passes(tmp_path):
    repo_dir = make_git_repo(tmp_path / "_upstream")
    yaml = PIPELINE_YAML.format(repo=repo_dir, minimum="2.0.0")
    ctx = make_ctx(tmp_path / "pkg", yaml)
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["fetch"] == "success"
    assert stage_status["transform"] == "success"
    assert stage_status["policy"] == "success"

    policy_stage = next(s for s in report.stages if s.name == "policy")
    assert policy_stage.details == [
        {"type": "vendor-constraints", "target": "ms", "status": "passed", "reason": None}
    ]


@requires_git_and_npm
@pytest.mark.integration
def test_fetch_then_vendor_then_policy_constraint_fails_closed(tmp_path):
    repo_dir = make_git_repo(tmp_path / "_upstream")
    # Require a version higher than what's actually vendored (2.0.0) --
    # simulates a security-fix pin regressing on a later upstream update.
    yaml = PIPELINE_YAML.format(repo=repo_dir, minimum="99.0.0")
    ctx = make_ctx(tmp_path / "pkg", yaml)
    spec = resolve_pipeline_spec(ctx)
    with pytest.raises(GorgetPolicyViolation, match="ms"):
        PipelineRunner(ctx, spec).run()
