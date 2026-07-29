"""Default paths (used when the corresponding --flag is omitted) and other
fixed constants."""

from __future__ import annotations

from pathlib import Path

DEFAULT_PACKAGE_DIR = Path("/package")
DEFAULT_PIPELINE_FILE = Path("/pipeline.yaml")
DEFAULT_GPG_KEYS_DIR = Path("/gpg-keys")
DEFAULT_OUTPUT_DIR = Path("/output")

CHECKSUM_ALGO = "sha512"

REPORT_FILENAME = "report.json"
SOURCES_MANIFEST_FILENAME = "sources"
