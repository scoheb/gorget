# Example: Verify stage (`gpg-signature` + re-publication detection)

Runnable, non-pytest example of gorget's Verify stage, built on the same GNU
Hello package as `../spec-source-demo`. Two things are demonstrated:

1. **`gpg-signature`**: a real, non-mocked signature check against GNU
   Hello's actual upstream maintainer key -- no synthetic keypair involved.
2. **Re-publication detection**: always-on when a `sources` file exists in
   the package directory,
   comparing a freshly-fetched artifact's checksum against what's already
   recorded there, failing closed on a mismatch unless cured by an
   `accepted-checksums:` entry.

Requires `rpmspec` (part of `rpm-build`), `gpg`, and network access to
`ftp.gnu.org`.

## Where `gpg-keys/hello-maintainer.asc` came from

GNU Hello's releases are signed by maintainer Reuben Thomas. His public key
(fingerprint `2409 3F01 6FFE 8602 EF44  9BB8 4C8E F3DA 3FD3 7230`, the same
key ID `hello-2.12.1.tar.gz.sig` is signed with) was fetched from a public
keyserver:

```bash
curl -s "https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x24093F016FFE8602EF449BB84C8EF3DA3FD37230" \
  -o gpg-keys/hello-maintainer.asc
```

This is exactly what a real `--gpg-keys-dir` directory looks like: one
armored public key file per trusted upstream, checked in once and reused
across releases.

## 1. Run: GPG signature verification

```bash
cd examples/verify-demo
source ../../.venv/bin/activate  # skip if gorget is already installed/on PATH

gorget --version 2.12.1 \
  --package-dir . \
  --pipeline-file hello.source-pipeline.yaml \
  --gpg-keys-dir gpg-keys \
  --output-dir /tmp/gorget-verify-output
```

```bash
cat /tmp/gorget-verify-output/report.json
```

The `verify` stage's `details` show a real, passing `gpg-signature` check:

```json
{
  "type": "gpg-signature",
  "target": "hello-2.12.1.tar.gz",
  "status": "passed",
  "reason": null
}
```

`GpgSignatureHandler` imports `gpg-keys/hello-maintainer.asc` into a fresh
throwaway GPG homedir (`tempfile.TemporaryDirectory()`) and runs
`gpg --verify` there -- nothing is written to a shared/persistent keyring.

Point `--gpg-keys-dir` at a keyring that doesn't have the real signer's key
to see it fail closed instead (any other real GPG key works -- the
signature just won't match):

```bash
mkdir -p /tmp/wrong-gpg-keys
gpg --homedir /tmp/wrong-gpg-keys-home --batch --passphrase "" \
  --quick-generate-key "Nobody <nobody@example.com>" default default never
gpg --homedir /tmp/wrong-gpg-keys-home --batch --export nobody@example.com \
  > /tmp/wrong-gpg-keys/hello-maintainer.asc

gorget --version 2.12.1 \
  --package-dir . \
  --pipeline-file hello.source-pipeline.yaml \
  --gpg-keys-dir /tmp/wrong-gpg-keys \
  --output-dir /tmp/gorget-verify-output
echo "exit code: $?"
```

```
error: Verification failed (1 check(s)):
- [gpg-signature] hello-2.12.1.tar.gz: gpg verification failed: gpg:
  Signature made Sun 29 May 2022 07:05:00 PM EDT ... gpg: Can't check
  signature: No public key
exit code: 2
```

This is a genuine `GorgetPolicyViolation` (exit 2) from a real `gpg --verify`
call, not a mocked failure path. A malformed/corrupt keyring file instead
produces a `gpg --import` failure, which is a config problem rather than a
policy violation (`GorgetTransientError`, exit 1).

## 2. Run: re-publication detection

This package's directory also has a `sources` file -- the dist-git-style
manifest recording what was already fetched and committed for this package.
Re-publication detection is **always on** when this file exists; no
`verify:` step is needed to opt in.

`sources` already contains the *correct* checksum for `hello-2.12.1.tar.gz`,
so the run above already exercised the passing path silently (no separate
`details` entry is emitted when everything matches -- see
`test_success_with_no_findings_when_sources_matches`). To see it fail
closed, simulate upstream silently replacing the tarball by corrupting the
recorded checksum:

```bash
cp sources /tmp/sources.bak
sed -i 's/= f871.*/= 00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000/' sources

gorget --version 2.12.1 \
  --package-dir . \
  --pipeline-file hello.source-pipeline.yaml \
  --gpg-keys-dir gpg-keys \
  --output-dir /tmp/gorget-verify-output
echo "exit code: $?"
```

```
error: Verification failed (1 check(s)):
- [republication] hello-2.12.1.tar.gz: hello-2.12.1.tar.gz was already
  published with sha512 000...000, but the freshly fetched copy has sha512
  f871e5f8...747749e2 instead -- upstream may have silently republished this
  file. If this is a legitimate re-publication, add to accepted-checksums:
  - file: 'hello-2.12.1.tar.gz'
    checksum: 'f871e5f8f64b0633ee45855c886ddf37565ae7a13d68a2d7d2df007e508355fcc85736b93c0274c4fed5e628a94d8a3f699925c7f44857dcd0aba78b747749e2'
    reason: "<why this re-publication is safe>"
```

Exit code 2 (policy violation). Now cure it by pasting that exact block
(with a real reason) into a copy of the pipeline YAML:

```bash
cp hello.source-pipeline.yaml /tmp/hello-accepted.yaml
cat >> /tmp/hello-accepted.yaml <<'EOF'

accepted-checksums:
  - file: "hello-2.12.1.tar.gz"
    checksum: "f871e5f8f64b0633ee45855c886ddf37565ae7a13d68a2d7d2df007e508355fcc85736b93c0274c4fed5e628a94d8a3f699925c7f44857dcd0aba78b747749e2"
    reason: "demo: simulated re-publication, real checksum accepted"
EOF

gorget --version 2.12.1 \
  --package-dir . \
  --pipeline-file /tmp/hello-accepted.yaml \
  --gpg-keys-dir gpg-keys \
  --output-dir /tmp/gorget-verify-output
```

Now it succeeds, and `report.json`'s `verify` details record the override
as an audit trail rather than a silent pass:

```json
{
  "type": "republication",
  "target": "hello-2.12.1.tar.gz",
  "status": "accepted",
  "reason": "Matches an accepted-checksums entry"
}
```

Restore the real `sources` file before running the demo again:

```bash
cp /tmp/sources.bak sources
```
