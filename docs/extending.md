# Add your own tool

Every tool in this project follows the same three-layer pattern:

```text
Moodle web-service function  →  method on Moodle in client.py  →  @mcp.tool in server.py
   (raw, huge JSON)                (trimmed to useful fields)        (what Claude sees)
```

This walkthrough adds `moodle_upcoming`, which returns everything on the Moodle calendar's *Upcoming* view: class sessions and course events as well as due dates. Nothing in the current tool set returns that.

## 0. Run from your clone

```bash
git clone https://github.com/ralstonraphael/moodle-mcp && cd moodle-mcp
uv tool install --force --editable .
```

`--editable` means the `moodle` and `moodle-mcp` commands run the code in this folder, so your edits take effect without reinstalling.

## 1. Find a function

Moodle exposes a few hundred functions, and your token can call some subset of them.

```bash
moodle functions calendar
```

```text
core_calendar_get_action_events_by_timesort
core_calendar_get_calendar_day_view
core_calendar_get_calendar_monthly_view
core_calendar_get_calendar_upcoming_view
...
```

The [Moodle web-service docs](https://docs.moodle.org/dev/Web_service_API_functions) describe each function's parameters. Your own site also documents them at `https://YOUR-MOODLE/admin/webservice/documentation.php`, if your account can see that page.

## 2. Call it raw

```bash
moodle call core_calendar_get_calendar_upcoming_view '{}'
```

You get a lot of JSON back. Each item in `events` has around 50 fields, and you want maybe five of them: `name`, `course.shortname`, `eventtype`, `timestart` and `url`.

Parameters go in the JSON. Nested lists and objects are fine, because the client flattens them into the `courseids[0]=…` form Moodle expects:

```bash
moodle call core_calendar_get_calendar_upcoming_view '{"courseid": 123}'
```

## 3. Add a client method

In `src/moodle_mcp/client.py`, inside `class Moodle`:

```python
    def upcoming_events(self, course_id: int | None = None) -> list[dict]:
        """Everything on the Moodle calendar's Upcoming view: due dates, class sessions, course events."""
        params = {"courseid": course_id} if course_id else {}
        res = self.call("core_calendar_get_calendar_upcoming_view", **params)
        return [{
            "name": _u(e.get("name")),
            "course": _u((e.get("course") or {}).get("shortname")),
            "type": e.get("eventtype"),
            "starts": fmt_time(e.get("timestart")),
            "url": e.get("url"),
        } for e in res.get("events", [])]
```

There are a few house rules here. The method returns plain dicts and lists. It keeps only the fields worth reading, so the full blob never reaches Claude. It uses `_u()` to un-escape HTML entities in names and `fmt_time()` for timestamps. If something goes wrong, `call()` already raises `MoodleError`.

## 4. Expose it as a tool

In `src/moodle_mcp/server.py`:

```python
@mcp.tool(annotations=READ)
def moodle_upcoming(course_id: int | None = None) -> Any:
    """Events on the Moodle calendar's Upcoming view (due dates, class sessions, course events).
    Pass course_id to limit it to one course."""
    return _guard(m().upcoming_events, course_id)
```

- **The docstring is the interface.** Claude picks tools by reading it, so say what the tool returns and when to use it.
- `annotations=READ` marks the tool read-only. For anything that writes, use `ToolAnnotations(readOnlyHint=False, destructiveHint=True, ...)` and tell Claude in the docstring to confirm with the user first.
- `_guard` turns `MoodleError` into an `{"error": ...}` result so Claude can see what went wrong.

## 5. Try it

Restart your Claude session, because MCP servers are loaded at startup, and ask *"what's on my Moodle calendar this week?"*. To click through tools without Claude:

```bash
npx @modelcontextprotocol/inspector moodle-mcp
```

Then update the tool count in `tests/test_server.py` and run `uv run pytest`.

## Ideas to build next

| Idea | Where to start |
| --- | --- |
| Calendar events (the example above) | `core_calendar_get_calendar_upcoming_view` |
| Review a finished quiz attempt | `mod_quiz_get_user_attempts`, then `mod_quiz_get_attempt_review` |
| Read Lesson activities (they fall back to a listing today) | `mod_lesson_get_pages`, `mod_lesson_get_page_data` |
| "What do I need on the final?" calculator | Pure Python on top of `moodle_grades` weights |
| Mark all notifications read ⚠️ writes | `core_message_mark_all_notifications_as_read` |
| A morning digest script | Call the client from a small script and run it with cron or Task Scheduler |
| Forum reply drafts ⚠️ writes | `mod_forum_add_discussion_post`. Keep a confirm step |

If you build something useful, open a pull request.
