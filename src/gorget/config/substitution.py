"""Variable substitution: ${VERSION}, ${VERSION_MAJOR}, ${VERSION_MINOR},
${VERSION_PATCH}, ${OLD_VERSION}, ${PACKAGE}, ${SPEC_FILE}, ${PACKAGE_DIR},
${UPSTREAM_REPO}.

Substitution runs once, on the raw dict/list/string tree produced by the YAML
loader, before it's turned into `PipelineSpec` dataclasses -- so the schema module
never needs to know about `${...}` tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gorget.exceptions import GorgetConfigError

_TOKEN_RE = re.compile(r"\$\{([A-Z_]+)\}")


@dataclass(frozen=True, kw_only=True)
class SubstitutionVars:
    version: str
    old_version: str | None
    package: str
    spec_file: str
    package_dir: str = ""
    upstream_repo: str = ""

    def _part(self, index: int) -> str:
        parts = self.version.split(".")
        return parts[index] if len(parts) > index else ""

    @property
    def version_major(self) -> str:
        return self._part(0)

    @property
    def version_minor(self) -> str:
        return self._part(1)

    @property
    def version_patch(self) -> str:
        return self._part(2)

    def as_mapping(self) -> dict[str, str]:
        return {
            "VERSION": self.version,
            "VERSION_MAJOR": self.version_major,
            "VERSION_MINOR": self.version_minor,
            "VERSION_PATCH": self.version_patch,
            "OLD_VERSION": self.old_version or "",
            "PACKAGE": self.package,
            "SPEC_FILE": self.spec_file,
            "PACKAGE_DIR": self.package_dir,
            "UPSTREAM_REPO": self.upstream_repo,
        }


def substitute_string(value: str, variables: SubstitutionVars) -> str:
    mapping = variables.as_mapping()

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in mapping:
            raise GorgetConfigError(f"Unknown substitution variable: ${{{name}}}")
        return mapping[name]

    return _TOKEN_RE.sub(_replace, value)


def walk_and_substitute(obj: object, variables: SubstitutionVars) -> object:
    if isinstance(obj, str):
        return substitute_string(obj, variables)
    if isinstance(obj, dict):
        return {key: walk_and_substitute(value, variables) for key, value in obj.items()}
    if isinstance(obj, list):
        return [walk_and_substitute(item, variables) for item in obj]
    return obj
