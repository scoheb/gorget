"""RunContext: resolved paths and substitution variables for one gorget invocation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from gorget import constants
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError


@dataclass(frozen=True, kw_only=True)
class RunContext:
    package_dir: Path
    pipeline_file: Path
    gpg_keys_dir: Path
    output_dir: Path
    dry_run: bool
    spec_path: Path
    vars: SubstitutionVars


def _resolve_path(value: str | None, default: Path) -> Path:
    return Path(value) if value is not None else default


def _find_spec_file(package_dir: Path) -> Path:
    if not package_dir.is_dir():
        raise GorgetConfigError(f"Package directory does not exist: {package_dir}")
    spec_files = sorted(package_dir.glob("*.spec"))
    if not spec_files:
        raise GorgetConfigError(f"No .spec file found in package directory: {package_dir}")
    if len(spec_files) > 1:
        names = ", ".join(p.name for p in spec_files)
        raise GorgetConfigError(f"Multiple .spec files found in {package_dir}: {names}")
    return spec_files[0]


def build_run_context(args: argparse.Namespace) -> RunContext:
    package_dir = _resolve_path(args.package_dir, constants.DEFAULT_PACKAGE_DIR)
    pipeline_file = _resolve_path(args.pipeline_file, constants.DEFAULT_PIPELINE_FILE)
    gpg_keys_dir = _resolve_path(args.gpg_keys_dir, constants.DEFAULT_GPG_KEYS_DIR)
    output_dir = _resolve_path(args.output_dir, constants.DEFAULT_OUTPUT_DIR)

    spec_path = _find_spec_file(package_dir)
    package_name = spec_path.stem

    substitution_vars = SubstitutionVars(
        version=args.pkg_version,
        old_version=args.old_version,
        package=package_name,
        spec_file=spec_path.name,
        package_dir=str(package_dir),
        upstream_repo=args.upstream_repo or "",
    )

    return RunContext(
        package_dir=package_dir,
        pipeline_file=pipeline_file,
        gpg_keys_dir=gpg_keys_dir,
        output_dir=output_dir,
        dry_run=args.dry_run,
        spec_path=spec_path,
        vars=substitution_vars,
    )
