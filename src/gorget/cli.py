"""Command-line entry point for gorget."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from gorget import __version__
from gorget.config.loader import build_pipeline_spec
from gorget.config.schema import PipelineSpec, SpecSourceStep
from gorget.context import RunContext, build_run_context
from gorget.exceptions import GorgetError
from gorget.pipeline.result import write_report_json
from gorget.pipeline.runner import PipelineRunner


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gorget",
        description="Containerized source-pipeline tool for RPM package supply-chain trust.",
    )
    parser.add_argument(
        "--version", dest="pkg_version", required=True, help="New upstream version to fetch"
    )
    parser.add_argument(
        "--old-version", dest="old_version", default=None, help="Previous upstream version"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run through the policy stage but skip emitting artifacts",
    )
    parser.add_argument("--package-dir", default=None, help="Override the /package mount")
    parser.add_argument("--pipeline-file", default=None, help="Override the /pipeline.yaml mount")
    parser.add_argument("--gpg-keys-dir", default=None, help="Override the /gpg-keys mount")
    parser.add_argument("--output-dir", default=None, help="Override the /output mount")
    parser.add_argument(
        "--upstream-repo",
        default=None,
        help="Canonical upstream repo URL, exposed as ${UPSTREAM_REPO}",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Trace every stage/step transition and subprocess command run, to stderr",
    )
    parser.add_argument(
        "--program-version",
        action="version",
        version=f"gorget {__version__}",
    )
    return parser


def _configure_debug_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[gorget debug] %(name)s: %(message)s"))
    logger = logging.getLogger("gorget")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)


def resolve_pipeline_spec(ctx: RunContext) -> PipelineSpec:
    """When no pipeline YAML is present, fetch every Source URL declared in the
    spec -- reusing `FetchStage`/`SpecSourceHandler`/`EmitStage` exactly as they'd
    run for a real pipeline YAML, rather than a separate code path.
    """
    if ctx.pipeline_file.exists():
        return build_pipeline_spec(ctx.pipeline_file, substitution_vars=ctx.vars)
    return PipelineSpec(fetch=[SpecSourceStep(index=None)])


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.debug:
        _configure_debug_logging()
    try:
        ctx = build_run_context(args)
        pipeline_spec = resolve_pipeline_spec(ctx)
        report = PipelineRunner(ctx, pipeline_spec).run()
    except GorgetError as exc:
        # partial_report is only ever set once ctx exists (PipelineRunner.run()
        # needs one to run at all) -- errors raised before that (e.g. an
        # invalid --package-dir) have none, so there's nothing to write yet.
        partial_report = exc.partial_report
        if partial_report is not None:
            if ctx.dry_run:
                print(json.dumps(partial_report.to_dict(), indent=2))
            else:
                try:
                    write_report_json(ctx.output_dir, partial_report.to_dict())
                except OSError as write_exc:
                    print(f"warning: could not write report.json: {write_exc}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    if ctx.dry_run:
        # Emit is skipped under --dry-run, so report.json never touches disk;
        # print it instead so a dry run isn't otherwise silent.
        print(json.dumps(report.to_dict(), indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
