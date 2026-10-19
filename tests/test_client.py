import base64
import io
import os
import zipfile
from datetime import datetime
from urllib.parse import parse_qs

import httpx
import pytest

from moodle_mcp import client as mc

# ---------------------------------------------------------------- tokens + config


def test_parse_token_accepts_a_bare_token():
    tok = "a1b2" * 8
    assert mc.parse_token(f"  {tok}\n") == tok


def test_parse_token_decodes_the_app_launch_link():
    tok = "c3d4" * 8
    payload = base64.b64encode(f"sitehash:::{tok}".encode()).decode()
    assert mc.parse_token(f"moodlemobile://token={payload}") == tok


def test_parse_token_rejects_junk():
    with pytest.raises(ValueError):
        mc.parse_token("not a token")


def test_save_load_and_clear_config(isolated_config):
    mc.save_config({"url": "https://moodle.example.edu", "token": "x" * 32})
    assert mc.load_config()["token"] == "x" * 32
    if os.name != "nt":
        assert isolated_config.stat().st_mode & 0o777 == 0o600
    assert mc.clear_config() is True
    assert mc.clear_config() is False


def test_env_vars_override_the_file(monkeypatch):
    mc.save_config({"url": "https://a.example.edu", "token": "x" * 32})
    monkeypatch.setenv("MOODLE_URL", "https://b.example.edu")
    assert mc.load_config()["url"] == "https://b.example.edu"


def test_missing_token_says_how_to_fix_it():
    with pytest.raises(mc.MoodleError) as e:
        mc.Moodle()
    assert e.value.code == "notoken"
    assert "moodle auth" in str(e.value)

# ---------------------------------------------------------------- formatting


def test_flatten_builds_moodle_style_params():
    out = {}
    mc._flatten("", {"courseids": [5, 7], "options": [{"name": "cmid", "value": 9}], "flag": True, "skip": None}, out)
    assert out == {"courseids[0]": 5, "courseids[1]": 7, "options[0][name]": "cmid", "options[0][value]": 9, "flag": 1}


def test_html_to_text_keeps_structure_and_links():
    text = mc.html_to_text(
        "<p>Read <b>chapter 3</b></p><ul><li>one</li><li>two</li></ul>"
        "<script>track()</script><a href='https://example.com/notes'>notes</a>"
    )
    assert "Read chapter 3" in text
    assert "- one" in text and "- two" in text
    assert "track()" not in text
    assert "<https://example.com/notes>" in text


@pytest.mark.parametrize("when, expected", [
    (datetime(2026, 3, 5, 9, 7), "Thu Mar 5 2026 9:07 AM"),
    (datetime(2026, 3, 5, 0, 30), "Thu Mar 5 2026 12:30 AM"),
    (datetime(2026, 3, 5, 23, 59), "Thu Mar 5 2026 11:59 PM"),
])
def test_fmt_time_is_portable(when, expected):
    assert mc.fmt_time(int(when.timestamp())) == expected


def test_fmt_time_handles_missing():
    assert mc.fmt_time(None) is None
    assert mc.fmt_time(0) is None

# ---------------------------------------------------------------- file text


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_extract_docx():
    xml = "<w:document><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p><w:p><w:t>World</w:t></w:p></w:body></w:document>"
    assert mc.extract_text(_zip({"word/document.xml": xml}), "", "notes.docx").split() == ["Hello", "World"]


def test_extract_pptx_keeps_slide_order():
    deck = _zip({f"ppt/slides/slide{i}.xml": f"<a:p>Slide {i} text</a:p>" for i in (10, 2, 1)})
    text = mc.extract_text(deck, "", "lecture.pptx")
    assert text.index("Slide 1 text") < text.index("Slide 2 text") < text.index("Slide 10 text")


def test_extract_plain_text_and_html():
    assert mc.extract_text(b"print('hi')", "", "lab.py") == "print('hi')"
    assert mc.extract_text(b"<h1>Week 3</h1><p>Read pp. 10-20</p>", "text/html", "page.html") == "Week 3\n\nRead pp. 10-20"


def test_extract_unknown_type_raises():
    with pytest.raises(mc.MoodleError):
        mc.extract_text(b"\x00\x01", "application/octet-stream", "video.mp4")

# ---------------------------------------------------------------- HTTP


def test_call_posts_token_function_and_flattened_params(fake_moodle):
    seen = {}

    def handler(req: httpx.Request):
        seen["path"] = req.url.path
        seen["form"] = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        return httpx.Response(200, json={"ok": True})

    c = fake_moodle(handler)
    assert c.call("mod_assign_get_assignments", courseids=[5, 7]) == {"ok": True}
    assert seen["path"] == "/webservice/rest/server.php"
    assert seen["form"]["wsfunction"] == "mod_assign_get_assignments"
    assert seen["form"]["moodlewsrestformat"] == "json"
    assert seen["form"]["courseids[1]"] == "7"


def test_expired_token_error_tells_you_to_reauth(fake_moodle):
    c = fake_moodle(lambda req: httpx.Response(200, json={
        "exception": "moodle_exception", "errorcode": "invalidtoken", "message": "Invalid token - token not found"}))
    with pytest.raises(mc.MoodleError) as e:
        c.call("core_webservice_get_site_info")
    assert e.value.code == "invalidtoken"
    assert "moodle auth" in str(e.value)


def test_functions_lists_and_filters(fake_moodle):
    site = {"userid": 1, "functions": [{"name": "mod_assign_get_assignments"},
                                       {"name": "core_calendar_get_calendar_upcoming_view"}]}
    c = fake_moodle(lambda req: httpx.Response(200, json=site))
    assert c.functions() == ["core_calendar_get_calendar_upcoming_view", "mod_assign_get_assignments"]
    assert c.functions("CALENDAR") == ["core_calendar_get_calendar_upcoming_view"]


def test_deadlines_are_trimmed(fake_moodle):
    event = {"activityname": "Lab 5 &amp; report", "course": {"id": 3, "shortname": "CHEM 111"},
             "modulename": "assign", "timesort": 4_102_444_800,
             "url": "https://moodle.example.edu/mod/assign/view.php?id=4821", "action": {"name": "Add submission"}}
    c = fake_moodle(lambda req: httpx.Response(200, json={"events": [event]}))
    [d] = c.deadlines(days_ahead=7)
    assert d["name"] == "Lab 5 & report"
    assert d["course"] == "CHEM 111"
    assert d["cmid"] == 4821
    assert d["overdue"] is False


def test_file_urls_get_the_webservice_path_and_token(fake_moodle):
    c = fake_moodle(lambda req: httpx.Response(200))
    url = c._file_url("https://moodle.example.edu/pluginfile.php/1/mod_resource/content/0/week3.pdf")
    assert "/webservice/pluginfile.php/" in url
    assert url.endswith("?token=" + "t" * 32)
