from src.thread_resolver import (
    extract_thread_finding_key,
    finding_key,
    open_thread_keys,
    select_threads_to_resolve,
)

AI_BODY = (
    "**HIGH — Security**\n\n"
    "**Hard-coded password**\n\n"
    "A password is stored in code.\n\n"
    "**Recommendation:** Use an environment variable."
)


def make_thread(
    thread_id="T1",
    *,
    resolved=False,
    outdated=False,
    body=AI_BODY,
    path="src/app.py",
    line=25,
    original_line=None,
):
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "path": path,
        "line": line,
        "originalLine": original_line,
        "comments": {"nodes": [{"body": body}]},
    }


def ids(selected):
    return [thread["id"] for thread, _ in selected]


def test_outdated_ai_thread_is_resolved():
    selected = select_threads_to_resolve([make_thread(outdated=True, line=None)])
    assert ids(selected) == ["T1"]
    assert "outdated" in selected[0][1]


def test_open_ai_thread_is_not_resolved_when_finding_is_missing():
    # Regression: a finding that the LLM did not repeat must NOT be closed.
    assert select_threads_to_resolve([make_thread(outdated=False)]) == []


def test_human_thread_is_never_resolved_even_if_outdated():
    human = make_thread(outdated=True, body="Please rename this variable.")
    assert select_threads_to_resolve([human]) == []


def test_already_resolved_thread_is_skipped():
    assert select_threads_to_resolve([make_thread(resolved=True, outdated=True)]) == []


def test_thread_without_id_is_skipped():
    thread = make_thread(outdated=True)
    thread["id"] = None
    assert select_threads_to_resolve([thread]) == []


def test_snake_case_fields_from_mcp_are_supported():
    thread = {
        "id": "T9",
        "is_resolved": False,
        "is_outdated": True,
        "comments": [{"body": AI_BODY}],
    }
    assert ids(select_threads_to_resolve([thread])) == ["T9"]


def test_non_dict_items_are_ignored():
    assert select_threads_to_resolve(["junk", None, 5]) == []


def test_key_uses_original_line_for_outdated_thread():
    thread = make_thread(outdated=True, line=None, original_line=25)
    assert extract_thread_finding_key(thread) == finding_key(
        "src/app.py", 25, "Hard-coded password"
    )


def test_open_keys_include_only_live_threads():
    live = make_thread("LIVE", line=10)
    outdated = make_thread("OLD", outdated=True, line=None, original_line=25)
    resolved = make_thread("DONE", resolved=True, line=30)

    keys = open_thread_keys([live, outdated, resolved])

    assert keys == {finding_key("src/app.py", 10, "Hard-coded password")}


def test_outdated_finding_can_be_reported_again():
    # Regression: after a thread becomes outdated, the same finding must not be
    # treated as a duplicate, otherwise it would never be posted again.
    outdated = make_thread(outdated=True, line=None, original_line=25)
    assert finding_key("src/app.py", 25, "Hard-coded password") not in open_thread_keys(
        [outdated]
    )


def test_just_resolved_thread_is_excluded_from_duplicates():
    thread = make_thread("T1", line=25)
    assert open_thread_keys([thread], exclude_ids={"T1"}) == set()
