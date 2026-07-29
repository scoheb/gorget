"""Real, non-mocked integration test for the Transform stage.

Clones a local git repo containing a real (tiny, stable) Go module, pins one
of its dependencies to a newer minimum version, and vendors it -- using the
actual `git` and `go` binaries, not mocked subprocess calls. This is also a
runnable example of the fetch -> transform (`vendor-pin` -> `vendor`) pipeline
YAML syntax; read `PIPELINE_YAML` below.

Requires `git` and `go` on PATH, plus network access to the real Go module
proxy (proxy.golang.org) to resolve rsc.io/quote's published versions --
skipped automatically if either tool is missing. Everything else about the
run is exactly what happens in production: no subprocess mocking anywhere.

Run just this test, with output:
    pytest tests/test_integration_transform.py -v -s
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from gorget.cli import resolve_pipeline_spec
from gorget.context import build_run_context
from gorget.pipeline.runner import PipelineRunner

requires_git_and_go = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("go") is None,
    reason="requires git and go on PATH",
)

# rsc.io/quote is the tiny, extremely stable module used in the official Go
# tutorials -- a safe, real-world dependency to demonstrate vendor-pin against.
PIPELINE_YAML = """
fetch:
  - type: git
    repo: "{repo}"
    ref: "main"

transform:
  - type: vendor-pin
    ecosystem: go
    pins:
      # Go module versions need the "v" prefix -- unlike npm/cargo, which
      # don't use one. Whatever minimum-version you write is passed through
      # to `go mod edit -require=<dependency>@<minimum-version>` verbatim.
      - dependency: "rsc.io/quote"
        minimum-version: "v1.5.2"
  - type: vendor
    ecosystem: go
"""


def _run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def demo_go_repo(tmp_path: Path) -> Path:
    """A tiny local git repo with a real Go module pinned to an old version
    of rsc.io/quote, so `vendor-pin` has something real to bump.
    """
    repo_dir = tmp_path / "demo-repo"
    repo_dir.mkdir()
    (repo_dir / "go.mod").write_text(
        "module example.com/demo\n\ngo 1.21\n\nrequire rsc.io/quote v1.0.0\n"
    )
    (repo_dir / "main.go").write_text(
        'package main\n\n'
        'import (\n'
        '\t"fmt"\n\n'
        '\t"rsc.io/quote"\n'
        ')\n\n'
        'func main() {\n'
        '\tfmt.Println(quote.Hello())\n'
        '}\n'
    )
    _run_git(["init", "-b", "main"], repo_dir)
    _run_git(["config", "user.email", "test@example.com"], repo_dir)
    _run_git(["config", "user.name", "Test"], repo_dir)
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "initial"], repo_dir)
    return repo_dir


def make_ctx(package_dir: Path, output_dir: Path, pipeline_yaml: str):
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "demo.spec").write_text("Name: demo\nVersion: 1.0.0\nRelease: 1\n")
    pipeline_file = package_dir.parent / "pipeline.yaml"
    pipeline_file.write_text(pipeline_yaml)
    args = argparse.Namespace(
        pkg_version="1.0.0",
        old_version=None,
        dry_run=False,
        package_dir=str(package_dir),
        pipeline_file=str(pipeline_file),
        gpg_keys_dir=str(package_dir.parent / "gpg-keys"),
        output_dir=str(output_dir),
        upstream_repo=None,
    )
    return build_run_context(args)


@pytest.mark.integration
@requires_git_and_go
def test_git_fetch_vendor_pin_vendor_with_real_tools(tmp_path, demo_go_repo, capsys):
    pipeline_yaml = PIPELINE_YAML.format(repo=str(demo_go_repo))
    ctx = make_ctx(tmp_path / "pkg", tmp_path / "output", pipeline_yaml)

    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    with capsys.disabled():
        print(f"\nStages: {[(s.name, s.status) for s in report.stages]}")
        print(f"Artifacts: {[a.output_name for a in report.artifacts]}")

    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["fetch"] == "success"
    assert stage_status["transform"] == "success"
    assert stage_status["emit"] == "success"

    output_dir = Path(ctx.output_dir)
    vendor_archive = output_dir / "demo-vendor.tar.gz"
    assert vendor_archive.exists()

    with tarfile.open(vendor_archive) as tar:
        modules_txt_name = next(n for n in tar.getnames() if n.endswith("modules.txt"))
        content = tar.extractfile(modules_txt_name).read().decode()

    with capsys.disabled():
        print(f"vendor/modules.txt:\n{content}")

    # go mod tidy resolves to *at least* the pinned minimum version.
    assert "rsc.io/quote v1.0.0" not in content
    assert "rsc.io/quote" in content
