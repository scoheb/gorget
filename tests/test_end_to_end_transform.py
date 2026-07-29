"""End-to-end: git (fetch) -> vendor-pin -> vendor (transform) through the real
PipelineRunner, with mocked subprocess calls -- confirms the pinned dependency
actually reaches the `go mod edit` call before vendoring runs, and that the
final emitted artifact is the vendor archive it produced.
"""

import argparse
import json
import subprocess
import tarfile
from pathlib import Path

from gorget.cli import resolve_pipeline_spec
from gorget.context import build_run_context
from gorget.pipeline.runner import PipelineRunner

PIPELINE_YAML = """
fetch:
  - type: git
    repo: "https://example.com/example.git"
    ref: "v${VERSION}"
transform:
  - type: vendor-pin
    ecosystem: go
    pins:
      - dependency: "golang.org/x/net"
        minimum-version: "0.23.0"
  - type: vendor
    ecosystem: go
"""


def make_ctx(tmp_path, pipeline_yaml, dry_run=False):
    (tmp_path / "foo.spec").write_text("Name: foo\nVersion: 1.2.3\nRelease: 1\n")
    pipeline_file = tmp_path / "pipeline.yaml"
    pipeline_file.write_text(pipeline_yaml)

    args = argparse.Namespace(
        pkg_version="1.2.3",
        old_version=None,
        dry_run=dry_run,
        package_dir=str(tmp_path),
        pipeline_file=str(pipeline_file),
        gpg_keys_dir=str(tmp_path / "gpg-keys"),
        output_dir=str(tmp_path / "output"),
        upstream_repo=None,
    )
    return build_run_context(args)


def _fake_run(calls):
    def run(args, cwd=None, env=None):
        calls.append((args, cwd))
        if args[:2] == ["git", "clone"]:
            dest = Path(args[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "go.mod").write_text(
                "module example\n\nrequire golang.org/x/net v0.20.0\n"
            )
            (dest / "go.sum").write_text("")
        elif "edit" in args:
            gomod = Path(cwd) / "go.mod"
            gomod.write_text(gomod.read_text().replace("v0.20.0", "v0.23.0"))
        elif args[-3:] == ["go", "mod", "vendor"]:
            vendor_dir = Path(cwd) / "vendor"
            vendor_dir.mkdir(parents=True, exist_ok=True)
            (vendor_dir / "modules.txt").write_text("golang.org/x/net v0.23.0\n")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    return run


def test_git_fetch_then_vendor_pin_then_vendor(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mocker.patch("gorget.fetch.vendor.commit_timestamp", return_value=1700000000)
    calls = []
    fake_run = _fake_run(calls)
    mocker.patch("gorget.fetch.git.run", side_effect=fake_run)
    mocker.patch("gorget.transform.vendor_pin.run", side_effect=fake_run)
    mocker.patch("gorget.fetch.vendor.go.run", side_effect=fake_run)

    ctx = make_ctx(tmp_path, PIPELINE_YAML)
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    fetch_result = next(s for s in report.stages if s.name == "fetch")
    transform_result = next(s for s in report.stages if s.name == "transform")
    assert fetch_result.status == "success"
    assert transform_result.status == "success"

    # The vendor-pin edit ran before vendor ran.
    edit_call = next(c for c in calls if "edit" in c[0])
    assert edit_call[0] == ["go", "mod", "edit", "-require=golang.org/x/net@0.23.0"]

    vendor_call_index = next(i for i, c in enumerate(calls) if c[0][-3:] == ["go", "mod", "vendor"])
    assert calls.index(edit_call) < vendor_call_index

    # Both the git-fetched source tarball and the vendor archive it produced
    # end up as artifacts; the vendor one reflects the pinned dependency.
    output_names = {a.output_name for a in report.artifacts}
    assert output_names == {"foo-1.2.3.tar.gz", "foo-vendor.tar.gz"}

    # Artifacts' original paths live under the pipeline's scratch work_dir,
    # already cleaned up by the time PipelineRunner.run() returns -- read the
    # copies Emit persisted to /output instead.
    output_dir = Path(ctx.output_dir)
    with tarfile.open(output_dir / "foo-vendor.tar.gz") as tar:
        modules_txt_name = next(n for n in tar.getnames() if n.endswith("modules.txt"))
        member = tar.extractfile(modules_txt_name)
        assert member is not None
        assert b"0.23.0" in member.read()

    report_json = json.loads((output_dir / "report.json").read_text())
    assert {a["output_name"] for a in report_json["artifacts"]} == output_names
