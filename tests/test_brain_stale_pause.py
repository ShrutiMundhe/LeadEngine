"""A Claude setup pause recorded by an earlier run clears once the CLI works.

Before the fix, a "Claude CLI not found" pause stored before the CLI was
installed stayed on the dashboard forever, because only the process that
recorded a pause could clear it.
"""

import asyncio
import json
import time

from sellbird import claude_runtime
from sellbird.brain import BRAIN_STATUS_KEY, Brain, parse_brain_status
from sellbird.state import StateManager


def _run(tmp_path, monkeypatch, stored: dict) -> dict:
    monkeypatch.setattr(claude_runtime, "check_cli", lambda env=None: "claude")

    async def go():
        state = StateManager(str(tmp_path / "t.db"))
        await state.init_db()
        await state.set_setting(BRAIN_STATUS_KEY, json.dumps(stored))
        brain = Brain(state)
        assert await brain.preflight() == ""
        return parse_brain_status(await state.get_setting(BRAIN_STATUS_KEY))

    return asyncio.run(go())


def test_stale_setup_pause_clears_on_first_good_preflight(tmp_path, monkeypatch):
    status = _run(tmp_path, monkeypatch, {
        "provider": "claude", "status": "paused", "kind": "setup",
        "reason": "Claude CLI not found on PATH.", "since": "2026-01-01T00:00:00Z"})
    assert status["status"] == "ok"


def test_unexpired_usage_limit_pause_is_kept(tmp_path, monkeypatch):
    status = _run(tmp_path, monkeypatch, {
        "provider": "claude", "status": "paused", "kind": "usage_limit",
        "reason": "usage limit", "until": time.time() + 3600})
    assert status["status"] == "paused"
