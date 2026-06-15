"""Event -> SSE wire-frame serialisation. Pure and dependency-free (no Starlette),
so it is unit-testable in isolation.

Every frame is ``{type, run_id, seq, ts, data, cost}`` where ``type`` is a lowercase
discriminator, ``data`` is the event payload, and ``cost`` is a live 8-key snapshot of
the run's token/cost usage (or ``None``).
"""

from __future__ import annotations

import dataclasses

from claudebackend.core import events

_TYPES = {
    events.DepGraphDone: "depgraph",
    events.PlanDone: "plan",
    events.StepStart: "step_start",
    events.FileRetry: "file_retry",
    events.SecurityReject: "security_reject",
    events.FileDone: "file_done",
    events.ProjectVerifyResult: "verify",
    events.Commit: "commit",
}


def event_type(event) -> str:
    """The lowercase wire discriminator for a pipeline event."""
    return _TYPES.get(type(event), type(event).__name__.lower())


def cost_snapshot(client) -> dict | None:
    """A live 8-key cost dict from the run's client, or ``None`` when unavailable.

    Identical shape to ``DevReport.to_dict()['cost']`` so the UI has one cost schema.
    """
    if client is None or not hasattr(client, "cost_report"):
        return None
    report = client.cost_report()
    u = report.usage
    return {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_read_tokens": u.cache_read_tokens,
        "cache_write_tokens": u.cache_write_tokens,
        "cost_usd": report.cost_usd if report.pricing_known else None,
        "pricing_known": report.pricing_known,
        "cache_hit_ratio": report.cache_hit_ratio,
        "calls": u.calls,
    }


def frame(type_: str, data: dict, *, run_id: str, seq: int, ts: float,
          cost: dict | None = None) -> dict:
    """Build a wire frame from explicit parts (for synthetic hello/done/error/graph)."""
    return {
        "type": type_,
        "run_id": run_id,
        "seq": seq,
        "ts": ts,
        "data": data,
        "cost": cost,
    }


def event_frame(event, *, run_id: str, seq: int, ts: float,
                cost: dict | None = None) -> dict:
    """Build a wire frame from a pipeline ``Event`` (``data`` = its ``asdict``)."""
    return frame(
        event_type(event),
        dataclasses.asdict(event),
        run_id=run_id,
        seq=seq,
        ts=ts,
        cost=cost,
    )
