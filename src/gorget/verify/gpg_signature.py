"""`gpg-signature` verify step: verify a fetched artifact against a detached
signature, using a keyring from the GPG keys directory (--gpg-keys-dir).

Imports the keyring into a fresh, throwaway GPG homedir per check (rather than
using --keyring directly against the keyring file) -- more robust across
keyring file formats and modern GPG's keybox-format quirks.
"""

from __future__ import annotations

import tempfile

from gorget.config.schema import GpgSignatureStep
from gorget.context import RunContext
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.pipeline.state import StageState
from gorget.util.subprocess_run import run
from gorget.verify.base import CheckResult


class GpgSignatureHandler:
    def run(self, step: GpgSignatureStep, ctx: RunContext, state: StageState) -> CheckResult:
        target = state.find_artifact(step.target)
        signature = state.find_artifact(step.signature)
        keyring_path = ctx.gpg_keys_dir / step.keyring
        if not keyring_path.is_file():
            raise GorgetConfigError(f"GPG keyring not found: {keyring_path}")

        with tempfile.TemporaryDirectory(prefix="gorget-gnupg-") as homedir:
            import_result = run(
                ["gpg", "--homedir", homedir, "--batch", "--import", str(keyring_path)]
            )
            if import_result.returncode != 0:
                raise GorgetTransientError(
                    f"gpg --import failed for {keyring_path}: {import_result.stderr.strip()}"
                )

            verify_result = run(
                [
                    "gpg", "--homedir", homedir, "--batch", "--verify",
                    str(signature.path), str(target.path),
                ]
            )

        if verify_result.returncode != 0:
            return CheckResult(
                type="gpg-signature",
                target=step.target,
                status="failed",
                reason=f"gpg verification failed: {verify_result.stderr.strip()}",
            )
        return CheckResult(type="gpg-signature", target=step.target, status="passed")
