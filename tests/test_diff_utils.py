import pytest

from src.diff_utils import (
    is_line_in_patch,
    parse_unified_patch,
    validate_finding_against_changed_files,
)
from tests.conftest import PATCH, make_finding


def test_parse_unified_patch_maps_new_file_lines():
    lines = parse_unified_patch(PATCH)
    assert lines == {
        1: "import os",
        2: "password = os.environ['PASSWORD']",
        3: "token = 'abc'",
        4: "print('ok')",
    }


def test_parse_handles_multiple_hunks_and_no_newline_marker():
    patch = "@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n@@ -10,2 +20,2 @@\n c\n+d"
    assert parse_unified_patch(patch) == {1: "b", 20: "c", 21: "d"}


def test_added_line_whose_content_starts_with_plus_is_counted():
    # Regression: "++i" is an added line containing "+i", not a file header.
    patch = "@@ -1,1 +1,3 @@\n x\n++i\n+y"
    assert parse_unified_patch(patch) == {1: "x", 2: "+i", 3: "y"}


def test_parse_empty_patch():
    assert parse_unified_patch(None) == {}
    assert parse_unified_patch("") == {}


@pytest.mark.parametrize(
    ("line", "expected"), [(1, True), (3, True), (4, True), (5, False), (None, False)]
)
def test_is_line_in_patch(line, expected):
    assert is_line_in_patch(PATCH, line) is expected


FILES = [
    {"filename": "app.py", "status": "modified", "patch": PATCH},
    {
        "filename": "new_name.py",
        "status": "renamed",
        "previous_filename": "old_name.py",
        "patch": PATCH,
    },
    {"filename": "gone.py", "status": "removed", "patch": "@@ -1 +0,0 @@\n-x"},
    {"filename": "image.png", "status": "added"},
]


def test_valid_line_is_accepted():
    target = validate_finding_against_changed_files(make_finding(file="app.py", line=3), FILES)
    assert target.ok and target.path == "app.py"


@pytest.mark.parametrize(
    ("file", "line", "reason"),
    [
        ("app.py", 99, "not in the diff"),
        ("app.py", None, "no line number"),
        ("", 3, "no file path"),
        ("other.py", 3, "not part of the pull request"),
        ("gone.py", 1, "was deleted"),
        ("image.png", 1, "no diff is available"),
    ],
)
def test_invalid_targets_are_rejected_with_reason(file, line, reason):
    target = validate_finding_against_changed_files(make_finding(file=file, line=line), FILES)
    assert not target.ok
    assert reason in target.reason


def test_renamed_file_maps_previous_name_to_new_path():
    target = validate_finding_against_changed_files(make_finding(file="old_name.py", line=2), FILES)
    assert target.ok and target.path == "new_name.py"


def test_git_prefixed_and_dot_slash_paths_are_normalised():
    for path in ("b/app.py", "./app.py", "/app.py"):
        assert validate_finding_against_changed_files(make_finding(file=path, line=2), FILES).ok
