"""Lightweight, non-blocking OpenTelemetry-compatible tracer for FRITZ! monitoring.

Emits standard OTLP HTTP/JSON traces to Tempo or Alloy with zero external C-dependencies,
enabling waterfall visualization of TR-064 calls, scrape cycles, and error root-causes.
"""
from __future__ import annotations

import os
import time
import uuid
import json
import threading
import queue
import urllib.request
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional
from loguru import logger

# Thread-local storage for active trace and span IDs
_thread_local = threading.local()

# Asynchronous batching queue for OTLP spans
_span_queue: queue.Queue[Dict[str, Any]] = queue.Queue(maxsize=1000)
_worker_started = False
_worker_lock = threading.Lock()


def _get_tempo_endpoint() -> str:
    ep = os.getenv("TEMPO_ENDPOINT", "http://tempo:3200/v1/traces")
    if not ep.endswith("/v1/traces") and not ep.endswith("/v1/traces/"):
        ep = ep.rstrip("/") + "/v1/traces"
    return ep


def current_trace_id() -> Optional[str]:
    """Return the active 32-char hex Trace ID in this thread context, if any."""
    return getattr(_thread_local, "trace_id", None)


def current_span_id() -> Optional[str]:
    """Return the active 16-char hex Span ID in this thread context, if any."""
    return getattr(_thread_local, "span_id", None)


def _sender_worker():
    """Background worker sending batched spans to Tempo via OTLP/HTTP."""
    endpoint = _get_tempo_endpoint()
    batch: List[Dict[str, Any]] = []

    while True:
        try:
            # Block waiting for first item
            item = _span_queue.get(timeout=2.0)
            batch.append(item)
            # Drain up to 50 more items without blocking
            while len(batch) < 50:
                try:
                    batch.append(_span_queue.get_nowait())
                except queue.Empty:
                    break
        except queue.Empty:
            continue
        except Exception:
            continue

        if not batch:
            continue

        # Format standard OTLP JSON payload
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "fritz-monitoring"}},
                            {"key": "service.version", "value": {"stringValue": "1.0.0"}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "fritz-collector", "version": "1.0.0"},
                            "spans": batch,
                        }
                    ],
                }
            ]
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                resp.read()
        except Exception:
            # Tracing failures are non-fatal and should never disrupt collection
            pass
        finally:
            batch.clear()


def _ensure_worker():
    global _worker_started
    if not _worker_started:
        with _worker_lock:
            if not _worker_started:
                t = threading.Thread(target=_sender_worker, daemon=True, name="tempo-trace-sender")
                t.start()
                _worker_started = True


@contextmanager
def trace_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Context manager for an OpenTelemetry span.

    Creates or inherits trace_id, measures execution duration, captures exceptions,
    and queues the span for asynchronous export to Tempo.
    """
    _ensure_worker()

    parent_trace_id = getattr(_thread_local, "trace_id", None)
    parent_span_id = getattr(_thread_local, "span_id", None)

    # Root span generates a new trace_id (32 hex chars)
    trace_id = parent_trace_id or uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]

    _thread_local.trace_id = trace_id
    _thread_local.span_id = span_id

    start_time_unix_nano = int(time.time() * 1e9)
    span_attrs = dict(attributes or {})
    span_status = {"code": 1}  # STATUS_CODE_OK

    try:
        yield {"trace_id": trace_id, "span_id": span_id, "attributes": span_attrs}
    except Exception as exc:
        span_status = {"code": 2, "message": str(exc)}  # STATUS_CODE_ERROR
        span_attrs["error"] = True
        span_attrs["exception.type"] = exc.__class__.__name__
        span_attrs["exception.message"] = str(exc)
        raise
    finally:
        end_time_unix_nano = int(time.time() * 1e9)

        # Restore previous span context in this thread
        _thread_local.trace_id = parent_trace_id
        _thread_local.span_id = parent_span_id

        # Convert attributes to OTLP KeyValue format
        otlp_attrs = []
        for k, v in span_attrs.items():
            if isinstance(v, bool):
                otlp_attrs.append({"key": k, "value": {"boolValue": v}})
            elif isinstance(v, int):
                otlp_attrs.append({"key": k, "value": {"intValue": v}})
            elif isinstance(v, float):
                otlp_attrs.append({"key": k, "value": {"doubleValue": v}})
            else:
                otlp_attrs.append({"key": k, "value": {"stringValue": str(v)}})

        span_record: Dict[str, Any] = {
            "traceId": trace_id,
            "spanId": span_id,
            "name": name,
            "startTimeUnixNano": str(start_time_unix_nano),
            "endTimeUnixNano": str(end_time_unix_nano),
            "status": span_status,
            "attributes": otlp_attrs,
        }
        if parent_span_id:
            span_record["parentSpanId"] = parent_span_id

        try:
            _span_queue.put_nowait(span_record)
        except queue.Full:
            pass
