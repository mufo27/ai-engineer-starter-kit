"""Minimal Prometheus metrics (no external client dep).

Maintains a small set of counters/summaries and renders the Prometheus text
exposition format for GET /metrics. Thread-safe enough for the demo; a real
deployment would use prometheus_client with multiprocess mode.
"""
from __future__ import annotations

import threading
from collections import defaultdict


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.http_requests: dict[tuple[str, str], int] = defaultdict(int)   # (path, status) -> count
        self.http_duration_sum: dict[str, float] = defaultdict(float)        # path -> seconds
        self.http_duration_count: dict[str, int] = defaultdict(int)
        self.llm_tokens: dict[tuple[str, str], int] = defaultdict(int)       # (tenant, kind) -> tokens
        self.llm_cost: dict[str, float] = defaultdict(float)                 # tenant -> usd
        self.llm_calls: dict[str, int] = defaultdict(int)                    # provider -> count

    def observe_request(self, path: str, status: int, duration_s: float) -> None:
        with self._lock:
            self.http_requests[(path, str(status))] += 1
            self.http_duration_sum[path] += duration_s
            self.http_duration_count[path] += 1

    def observe_llm(
        self, tenant_id: str, provider: str, prompt_tokens: int, completion_tokens: int, cost_usd: float
    ) -> None:
        with self._lock:
            self.llm_tokens[(tenant_id, "prompt")] += prompt_tokens
            self.llm_tokens[(tenant_id, "completion")] += completion_tokens
            self.llm_cost[tenant_id] += cost_usd
            self.llm_calls[provider] += 1

    def render(self) -> str:
        with self._lock:
            lines: list[str] = []
            lines.append("# HELP http_requests_total Total HTTP requests by path and status.")
            lines.append("# TYPE http_requests_total counter")
            for (path, status), c in self.http_requests.items():
                lines.append(f'http_requests_total{{path="{path}",status="{status}"}} {c}')
            lines.append("# HELP http_request_duration_seconds_sum Latency sum by path.")
            lines.append("# TYPE http_request_duration_seconds summary")
            for path in self.http_duration_sum:
                lines.append(f'http_request_duration_seconds_sum{{path="{path}"}} {self.http_duration_sum[path]:.6f}')
                lines.append(f'http_request_duration_seconds_count{{path="{path}"}} {self.http_duration_count[path]}')
            lines.append("# HELP llm_tokens_total LLM tokens by tenant and kind.")
            lines.append("# TYPE llm_tokens_total counter")
            for (tenant, kind), c in self.llm_tokens.items():
                lines.append(f'llm_tokens_total{{tenant_id="{tenant}",kind="{kind}"}} {c}')
            lines.append("# HELP llm_cost_usd_total Cumulative LLM cost by tenant.")
            lines.append("# TYPE llm_cost_usd_total counter")
            for tenant, v in self.llm_cost.items():
                lines.append(f'llm_cost_usd_total{{tenant_id="{tenant}"}} {v:.8f}')
            lines.append("# HELP llm_calls_total LLM calls by provider.")
            lines.append("# TYPE llm_calls_total counter")
            for provider, c in self.llm_calls.items():
                lines.append(f'llm_calls_total{{provider="{provider}"}} {c}')
            return "\n".join(lines) + "\n"


METRICS = Metrics()
