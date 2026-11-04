from src.context_builder import (
    build_review_context,
    describe_pull_request,
    render_hunk,
    split_hunks,
)
from tests.conftest import PATCH

DETAILS = {
    "title": "Add login",
    "body": "Implements login.",
    "user": {"login": "dev"},
    "base": {"ref": "main"},
    "head": {"ref": "feature"},
}


def test_render_hunk_numbers_new_file_lines():
    rendered = render_hunk(split_hunks(PATCH)[0]).splitlines()
    assert rendered[0] == "@@ -1,3 +1,4 @@"
    assert rendered[1] == "     1  import os"
    assert rendered[2].strip() == "-password = 'x'"
    assert rendered[3] == "     2 +password = os.environ['PASSWORD']"
    assert rendered[5] == "     4  print('ok')"


def test_describe_pull_request_uses_selected_fields_and_unwraps():
    text = describe_pull_request({"pull_request": DETAILS})
    assert "Title: Add login" in text and "Base: main" in text and "Implements login." in text
    assert "(details unavailable)" in describe_pull_request("oops")


def test_context_sends_each_patch_once_without_raw_diff():
    files = [{"filename": "app.py", "status": "modified", "patch": PATCH}]
    ctx = build_review_context(DETAILS, files, 10_000, raw_diff="SHOULD NOT APPEAR")

    assert ctx.text.count("password = os.environ") == 1
    assert "SHOULD NOT APPEAR" not in ctx.text
    assert ctx.included_files == ["app.py"] and not ctx.truncated


def test_truncation_keeps_whole_hunks_and_lists_omitted_files():
    big_hunk = "@@ -1 +1,200 @@\n" + "\n".join(f"+line {i}" for i in range(200))
    files = [
        {"filename": "small.py", "patch": PATCH},
        {"filename": "big.py", "patch": big_hunk},
    ]

    ctx = build_review_context(DETAILS, files, 1500)

    assert ctx.truncated
    assert ctx.included_files == ["small.py"]
    assert ctx.omitted_files == ["big.py"]
    assert "## Files not included (context limit)\n- big.py" in ctx.text
    assert "line 199" not in ctx.text  # no partial hunk
    assert len(ctx.text) <= 1500 + 200


def test_partial_file_keeps_leading_hunks():
    patch = PATCH + "\n@@ -50 +51,100 @@\n" + "\n".join(f"+x{i}" for i in range(100))
    ctx = build_review_context(DETAILS, [{"filename": "app.py", "patch": patch}], 900)

    assert ctx.truncated and ctx.included_files == ["app.py"]
    assert "token = 'abc'" in ctx.text
    assert "1 more hunk(s) omitted" in ctx.text


def test_raw_diff_fallback_cuts_at_hunk_boundary():
    diff = "diff --git a/a b/a\n@@ -1 +1 @@\n+a\n" + "@@ -9 +9 @@\n" + "+b" * 500
    ctx = build_review_context(DETAILS, [{"filename": "a"}], 400, raw_diff=diff)

    assert ctx.truncated
    assert "+a" in ctx.text and "+b+b" not in ctx.text


def test_code_fence_survives_backticks_in_patch():
    patch = "@@ -1 +1 @@\n+```python"
    ctx = build_review_context(DETAILS, [{"filename": "README.md", "patch": patch}], 5000)
    assert "````diff" in ctx.text
