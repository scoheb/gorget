import pytest

from gorget.config.substitution import SubstitutionVars, substitute_string, walk_and_substitute
from gorget.exceptions import GorgetConfigError


def make_vars(
    version="1.2.3",
    old_version="1.2.2",
    package="foo",
    spec_file="foo.spec",
    package_dir="/pkg",
    upstream_repo="https://example.com/org/foo",
):
    return SubstitutionVars(
        version=version,
        old_version=old_version,
        package=package,
        spec_file=spec_file,
        package_dir=package_dir,
        upstream_repo=upstream_repo,
    )


@pytest.mark.parametrize(
    ("version", "major", "minor", "patch"),
    [
        ("1.2.3", "1", "2", "3"),
        ("1.2", "1", "2", ""),
        ("1", "1", "", ""),
        ("1.2.3.4", "1", "2", "3"),
    ],
)
def test_version_component_derivation(version, major, minor, patch):
    v = make_vars(version=version)
    assert v.version_major == major
    assert v.version_minor == minor
    assert v.version_patch == patch


def test_substitute_string_replaces_all_known_tokens():
    v = make_vars()
    result = substitute_string(
        "${PACKAGE}-${VERSION} (was ${OLD_VERSION}) major=${VERSION_MAJOR} "
        "spec=${SPEC_FILE} dir=${PACKAGE_DIR} repo=${UPSTREAM_REPO}",
        v,
    )
    assert result == (
        "foo-1.2.3 (was 1.2.2) major=1 spec=foo.spec dir=/pkg repo=https://example.com/org/foo"
    )


def test_substitute_string_old_version_none_becomes_empty():
    v = make_vars(old_version=None)
    assert substitute_string("${OLD_VERSION}", v) == ""


def test_substitute_string_unknown_token_raises():
    v = make_vars()
    with pytest.raises(GorgetConfigError, match="TYPO"):
        substitute_string("${TYPO}", v)


def test_walk_and_substitute_nested_structure():
    v = make_vars()
    obj = {
        "url": "https://example.com/${PACKAGE}-${VERSION}.tar.gz",
        "steps": [{"ref": "v${VERSION}"}, {"count": 3, "enabled": True, "nothing": None}],
    }
    result = walk_and_substitute(obj, v)
    assert result == {
        "url": "https://example.com/foo-1.2.3.tar.gz",
        "steps": [{"ref": "v1.2.3"}, {"count": 3, "enabled": True, "nothing": None}],
    }
