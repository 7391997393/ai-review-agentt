import pytest

from src.thread_resolver import (
    AI_COMMENT_MARKER,
    existing_thread_keys,
    extract_thread_finding_key,
    finding_key,
    format_inline_comment,
    is_ai_review_thread,
    open_thread_keys,
    parse_comment_title,
    sanitize_title,
    select_threads_to_reopen,
    select_threads_to_resolve,
    summary_fingerprint,
    summary_fingerprints_from_reviews,
    summary_marker,
    threads_from_mcp_response,
)
from tests.conftest import AGENT, AI_BODY, make_finding, make_thread


def ids(selected):
    return [thread["id"] for thread, _ in selected]


# -- finding identity ------------------------------------------------------------


def test_finding_key_is_case_and_whitespace_insensitive():
    assert finding_key("src/app.py", 42, "SQL  Injection") == finding_key(
        "src/app.py", 42, "sql injection"
    )
    assert finding_key("src/app.py", 42, "x").startswith("src/app.py:42:")


def test_finding_key_supports_missing_line():
    assert finding_key("app.py", None, "Title") == "app.py::title"
    assert finding_key("app.py", None, "Title") != finding_key("app.py", 1, "Title")


def test_summary_fingerprint_ignores_line_and_description():
    a = make_finding(line=3, description="one wording")
    b = make_finding(line=None, description="a completely different wording")
    assert summary_fingerprint(a) == summary_fingerprint(b)
    assert summary_fingerprint(a) != summary_fingerprint(make_finding(title="Other"))


# -- format <-> parse round trip ---------------------------------------------------


@pytest.mark.parametrize(
    "title",
    ["Hard-coded token", "Title with **bold** and — dash", "  multi\nline\ttitle  "],
)
def test_inline_comment_round_trips_title(title):
    finding = make_finding(title=title, file="app.py", line=3)
    body = format_inline_comment(finding)

    assert AI_COMMENT_MARKER in body
    assert parse_comment_title(body) == sanitize_title(title)
    thread = make_thread(body=body, path="app.py", line=3)
    assert extract_thread_finding_key(thread) == finding_key("app.py", 3, title)


def test_inline_comment_neutralises_mentions():
    body = format_inline_comment(make_finding(description="cc @org/team"))
    assert "@org/team" not in body


def test_legacy_comment_title_is_parsed():
    assert parse_comment_title(AI_BODY) == "Hard-coded password"
    assert parse_comment_title("no bold lines") is None


# -- AI thread identification ------------------------------------------------------


def test_ai_thread_detected_by_marker_and_legacy_format():
    assert is_ai_review_thread(make_thread(body=f"x\n{AI_COMMENT_MARKER}"))
    assert is_ai_review_thread(make_thread(body=AI_BODY))  # exact legacy layout
    # Loose look-alikes written by people are NOT AI threads:
    for body in ("**Recommendation:** Fix", "**Nit** — please rename", "**HIGH — Security**"):
        assert not is_ai_review_thread(make_thread(body=body)), body
    assert not is_ai_review_thread({"comments": {"nodes": [{"body": "Just a comment"}]}})
    assert not is_ai_review_thread({"comments": []})


def test_human_thread_with_ai_reply_is_not_ai_thread():
    human = make_thread(
        body="Please rename this variable.",
        extra_comments=[{"body": AI_BODY}],
    )
    assert not is_ai_review_thread(human)


def test_author_must_match_agent_login_when_known():
    thread = make_thread(author="someone-else")
    assert is_ai_review_thread(thread)  # login unknown -> format decides
    assert not is_ai_review_thread(make_thread(author=None), agent_login="ai-bot")
    assert not is_ai_review_thread(thread, agent_login="ai-bot")
    assert is_ai_review_thread(make_thread(author="ai-bot"), agent_login="ai-bot")


# -- resolve selection -------------------------------------------------------------


def test_outdated_ai_thread_is_resolved():
    selected = select_threads_to_resolve([make_thread(outdated=True, line=None)], AGENT)
    assert ids(selected) == ["T1"]
    assert "outdated" in selected[0][1]


def test_open_ai_thread_is_not_resolved_when_finding_is_missing():
    # Regression: a finding the LLM did not repeat must NOT be closed.
    assert select_threads_to_resolve([make_thread(outdated=False)], AGENT) == []


def test_human_thread_is_never_resolved_even_if_outdated():
    human = make_thread(outdated=True, body="Please rename this variable.")
    assert select_threads_to_resolve([human], AGENT) == []


def test_other_authors_ai_formatted_thread_is_not_resolved():
    thread = make_thread(outdated=True, author="human-reviewer")
    assert select_threads_to_resolve([thread], agent_login="ai-bot") == []


def test_already_resolved_thread_is_skipped():
    assert select_threads_to_resolve([make_thread(resolved=True, outdated=True)], AGENT) == []


def test_thread_without_id_is_skipped():
    assert select_threads_to_resolve([make_thread(thread_id=None, outdated=True)], AGENT) == []


def test_snake_case_fields_from_mcp_are_supported():
    thread = {
        "id": "T9",
        "is_resolved": False,
        "is_outdated": True,
        "comments": [{"body": AI_BODY, "author": "ai-bot"}],  # MCP: author is a string
    }
    thread = threads_from_mcp_response({"review_threads": [thread]})[0]
    assert ids(select_threads_to_resolve([thread], AGENT)) == ["T9"]


def test_non_dict_items_are_ignored():
    assert select_threads_to_resolve(["junk", None, 5], AGENT) == []


# -- reopen selection --------------------------------------------------------------


def test_resolved_current_thread_is_reopened_when_finding_returns():
    thread = make_thread("R1", resolved=True, line=25)
    key = finding_key("src/app.py", 25, "Hard-coded password")

    assert ids(select_threads_to_reopen([thread], {key}, AGENT)) == ["R1"]
    assert select_threads_to_reopen([thread], set(), AGENT) == []


def test_reopen_skips_outdated_open_and_human_threads():
    key = finding_key("src/app.py", 25, "Hard-coded password")
    threads = [
        make_thread("OUT", resolved=True, outdated=True, line=None, original_line=25),
        make_thread("OPEN", resolved=False, line=25),
        make_thread("HUMAN", resolved=True, body="**Hard-coded password**\n\nhuman note"),
    ]
    assert select_threads_to_reopen(threads, {key}, AGENT) == []


# -- duplicate keys ----------------------------------------------------------------


def test_key_uses_original_line_for_outdated_thread():
    thread = make_thread(outdated=True, line=None, original_line=25)
    assert extract_thread_finding_key(thread) == finding_key(
        "src/app.py", 25, "Hard-coded password"
    )


def test_open_keys_include_only_live_threads():
    live = make_thread("LIVE", line=10)
    outdated = make_thread("OLD", outdated=True, line=None, original_line=25)
    resolved = make_thread("DONE", resolved=True, line=30)

    assert open_thread_keys([live, outdated, resolved]) == {
        finding_key("src/app.py", 10, "Hard-coded password")
    }


def test_existing_keys_count_resolved_threads_but_not_outdated_or_human():
    resolved = make_thread("DONE", resolved=True, line=30)
    outdated = make_thread("OLD", outdated=True, line=None, original_line=25)
    human = make_thread("H", body="**Some title**\n\nhuman text", line=5)

    assert existing_thread_keys([resolved, outdated, human]) == {
        finding_key("src/app.py", 30, "Hard-coded password")
    }


def test_outdated_finding_can_be_reported_again():
    outdated = make_thread(outdated=True, line=None, original_line=25)
    key = finding_key("src/app.py", 25, "Hard-coded password")
    assert key not in existing_thread_keys([outdated])


def test_just_resolved_thread_is_excluded_from_duplicates():
    assert open_thread_keys([make_thread("T1", line=25)], exclude_ids={"T1"}) == set()


# -- summary fingerprints ----------------------------------------------------------


def test_summary_fingerprints_only_from_agent_reviews():
    reviews = [
        {"body": summary_marker("aaaaaaaaaaaaaaaa"), "author": {"login": "ai-bot"}},
        {"body": summary_marker("bbbbbbbbbbbbbbbb"), "author": {"login": "human"}},
        {"body": None},
        "junk",
    ]
    assert summary_fingerprints_from_reviews(reviews, "ai-bot") == {"aaaaaaaaaaaaaaaa"}
    assert len(summary_fingerprints_from_reviews(reviews)) == 2


# -- MCP response normalisation -----------------------------------------------------


def test_threads_from_mcp_response_shapes():
    threads = [make_thread()]
    assert threads_from_mcp_response({"review_threads": threads})[0]["id"] == "T1"

    comments = [{"path": "a.py", "line": 3, "body": AI_BODY}]
    pseudo = threads_from_mcp_response({"comments": comments})
    assert extract_thread_finding_key(pseudo[0]) == finding_key("a.py", 3, "Hard-coded password")
    assert pseudo[0]["id"] is None

    assert threads_from_mcp_response("unexpected text") is None
