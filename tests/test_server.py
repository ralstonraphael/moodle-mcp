import asyncio

from moodle_mcp import server

WRITES = {"moodle_submit_assignment", "moodle_call", "moodle_download"}


def _tools():
    return asyncio.run(server.mcp.list_tools())


def test_all_tools_registered():
    names = {t.name for t in _tools()}
    assert len(names) == 17  # bump this when you add a tool
    assert {"moodle_deadlines", "moodle_read", "moodle_functions"} <= names


def test_only_the_writing_tools_are_marked_writable():
    writable = {t.name for t in _tools() if not (t.annotations and t.annotations.readOnlyHint)}
    assert writable == WRITES


def test_every_tool_has_a_description():
    assert all((t.description or "").strip() for t in _tools())
