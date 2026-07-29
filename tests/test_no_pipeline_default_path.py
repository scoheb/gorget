import argparse

from gorget.cli import resolve_pipeline_spec
from gorget.config.schema import PipelineSpec, SpecSourceStep
from gorget.context import build_run_context


def make_ctx(tmp_path, pipeline_file=None):
    (tmp_path / "foo.spec").write_text("Name: foo\nVersion: 1.0.0\n")
    args = argparse.Namespace(
        pkg_version="1.2.3",
        old_version=None,
        dry_run=False,
        package_dir=str(tmp_path),
        pipeline_file=pipeline_file or str(tmp_path / "does-not-exist.yaml"),
        gpg_keys_dir=str(tmp_path / "gpg-keys"),
        output_dir=str(tmp_path / "output"),
        upstream_repo=None,
    )
    return build_run_context(args)


def test_resolve_pipeline_spec_synthesizes_fetch_all_when_no_yaml(tmp_path):
    ctx = make_ctx(tmp_path)
    spec = resolve_pipeline_spec(ctx)
    assert spec == PipelineSpec(fetch=[SpecSourceStep(index=None)])


def test_resolve_pipeline_spec_loads_real_yaml_when_present(tmp_path):
    pipeline_file = tmp_path / "pipeline.yaml"
    pipeline_file.write_text("fetch:\n  - type: spec-source\n    index: 0\n")
    ctx = make_ctx(tmp_path, pipeline_file=str(pipeline_file))
    spec = resolve_pipeline_spec(ctx)
    assert spec == PipelineSpec(fetch=[SpecSourceStep(index=0)])


def test_no_yaml_end_to_end_fetches_all_spec_sources(tmp_path, mocker):
    import subprocess

    (tmp_path / "foo.spec").write_text("Name: foo\nVersion: 1.2.3\n")
    mocker.patch(
        "gorget.specfile.run",
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "Source0: https://example.com/foo-1.2.3.tar.gz\n"
                "Source1: https://example.com/extra.tar.gz\n"
            ),
            stderr="",
        ),
    )
    mocker.patch(
        "gorget.fetch.spec_source.download_to",
        side_effect=lambda url, dest: dest.write_bytes(b"data"),
    )

    ctx = make_ctx(tmp_path)
    spec = resolve_pipeline_spec(ctx)

    from gorget.pipeline.runner import PipelineRunner

    report = PipelineRunner(ctx, spec).run()

    output_names = {a.output_name for a in report.artifacts}
    assert output_names == {"foo-1.2.3.tar.gz", "extra.tar.gz"}
    assert (ctx.output_dir / "foo-1.2.3.tar.gz").exists()
    assert (ctx.output_dir / "extra.tar.gz").exists()
