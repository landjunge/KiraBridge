#!/usr/bin/env python3
"""Export content-free tunnel histograms from loopback metrics or a private capture."""

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_LABELS = {
    "channel",
    "latency_type",
    "request_kind",
    "request_method",
    "tunnel_service_status",
    "http_request_method",
    "http_response_status_code",
    "http_route",
    "network_protocol_version",
}


def histograms(text, prefix, multiplier):
    groups = {}
    for line in text.splitlines():
        if not line.startswith(prefix + "_"):
            continue
        metric = line.split("{", 1)[0].split(" ", 1)[0]
        labels = dict(re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', line))
        upper = labels.pop("le", None)
        labels = {k: v for k, v in labels.items() if k in ALLOWED_LABELS}
        if "http_route" in labels:
            labels["http_route"] = re.sub(
                r"tunnel_[A-Za-z0-9_-]+", "{tunnel_id}", labels["http_route"]
            )
        key = json.dumps(labels, sort_keys=True)
        item = groups.setdefault(key, {"labels": labels, "buckets": []})
        value = float(line.rsplit(" ", 1)[-1])
        if metric == prefix + "_count":
            item["count"] = int(value)
        elif metric == prefix + "_sum":
            item["sum_ms"] = value * multiplier
        elif metric == prefix + "_bucket":
            item["buckets"].append(
                {
                    "upper_ms": float(upper) * multiplier if upper != "+Inf" else None,
                    "cumulative_count": int(value),
                }
            )
    for item in groups.values():
        count = item.get("count", 0)
        item["mean_ms"] = item.get("sum_ms", 0) / count if count else None
        item["buckets"].sort(key=lambda b: float("inf") if b["upper_ms"] is None else b["upper_ms"])
        for name, quantile in (("p50", 0.50), ("p95", 0.95)):
            item[name + "_histogram_upper_ms"] = (
                next(
                    (
                        bucket["upper_ms"]
                        for bucket in item["buckets"]
                        if bucket["cumulative_count"] >= quantile * count
                    ),
                    None,
                )
                if count
                else None
            )
    return list(groups.values())


def capture(text):
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": (
            "Tunnel process-lifetime cumulative histograms; not per-Voice or per-model timings"
        ),
        "quantiles": "Histogram bucket upper bounds, not exact sample percentiles",
        "privacy": "Only selected metric labels; tunnel identifiers and payloads omitted",
        "command_latency": histograms(text, "command_end_to_end_latency_milliseconds", 1),
        "controlplane_http_latency": histograms(text, "http_client_request_duration_seconds", 1000),
        "limits": [
            "enqueue_to_response uses control-plane enqueue wall clock and host clock",
            "poll_to_response includes local execution and response POST",
            "HTTP poll durations include idle long-poll waiting and are not request delivery delay",
            "Process totals include all callers since tunnel startup",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--metrics-file", type=Path)
    source.add_argument("--base-url")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.metrics_file:
        if args.output.resolve() == args.metrics_file.resolve():
            parser.error("Output must not overwrite input")
        raw = args.metrics_file.read_text()
    else:
        url = urlsplit(args.base_url)
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            parser.error("Only an unauthenticated explicit HTTP loopback endpoint is allowed")
        with urllib.request.urlopen(args.base_url.rstrip("/") + "/metrics", timeout=5) as response:
            payload = response.read(3 * 1024 * 1024 + 1)
        if len(payload) > 3 * 1024 * 1024:
            parser.error("Metrics exceed bound")
        raw = payload.decode()
    data = capture(raw)
    args.output.write_text(json.dumps(data, indent=2) + "\n")
    print(
        json.dumps(
            {
                "command_groups": len(data["command_latency"]),
                "http_groups": len(data["controlplane_http_latency"]),
            }
        )
    )
