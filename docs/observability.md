# Observability and Monitoring Guide

---

## Overview

Claude Bridge ships a built-in observability stack based on open standards:

- **Prometheus** — metrics collection and scraping
- **Jaeger** — distributed tracing (OTLP-compatible)
- **OTLP** — vendor-neutral telemetry export
- **SSE** — real-time event stream for dashboards

All endpoints are HTTP and do not require authentication in local development setups.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_BRIDGE_TRACING` | `none` | Tracing level: `none`, `basic`, `detailed` |
| `CLAUDE_BRIDGE_TRACING_SAMPLE_RATE` | `1.0` | Tracing sample rate (0.0-1.0) for detailed tracing |
| `CLAUDE_BRIDGE_OTLP_ENDPOINT` | _(none)_ | OTLP collector endpoint (e.g. `http://localhost:4317`) |
| `CLAUDE_BRIDGE_OTEL_SERVICE_NAME` | `claude-bridge` | Service name injected into trace spans |
| `CLAUDE_BRIDGE_OTEL_METRICS_ENDPOINT` | _(none)_ | OTLP metrics export endpoint |
| `CLAUDE_BRIDGE_METRICS_ENABLED` | `true` | Enable/disable metrics collection |
| `CLAUDE_BRIDGE_HEALTH_HOST` | `127.0.0.1` | Host to bind health endpoints |
| `CLAUDE_BRIDGE_HEALTH_PORT` | `8766` | Port for health and metrics endpoints |
| `CLAUDE_BRIDGE_DASHBOARD_HOST` | `127.0.0.1` | Host to bind dashboard server |
| `CLAUDE_BRIDGE_DASHBOARD_PORT` | `8765` | Port for dashboard server |
| `CLAUDE_BRIDGE_DASHBOARD_LAN` | `false` | Allow dashboard to bind to non-loopback addresses |
| `CLAUDE_BRIDGE_DASHBOARD_AUTO_OPEN` | `true` | Auto-open browser dashboard on startup |

### Tracing Levels

- `none` — no telemetry collected
- `basic` — request-scoped spans with latency, status, and tool name
- `detailed` — full parameter capture, path traversal events, shell command args (may contain sensitive data; audit logs are the appropriate venue for that)

---

## Endpoints

### Health Probes

| Path | Description |
|------|-------------|
| `GET /healthz/live` | Liveness probe — returns `200` if process is alive |
| `GET /healthz/ready` | Readiness probe — returns `200` if ready to serve requests |
| `GET /healthz` | Combined health status (live + ready) |

All health endpoints return JSON:

```json
{
  "status": "ok",
  "timestamp": "2026-05-19T10:00:00Z"
}
```

### Metrics

```
GET /metrics
```

Exposes Prometheus-format metrics. Example output:

```
# HELP claude_bridge_tool_calls_total Total tool calls
# TYPE claude_bridge_tool_calls_total counter
claude_bridge_tool_calls_total{tool="read"} 42

# HELP claude_bridge_tool_duration_seconds Tool call duration
# TYPE claude_bridge_tool_duration_seconds histogram
claude_bridge_tool_duration_seconds_bucket{tool="read",le="0.1"} 38
claude_bridge_tool_duration_seconds_bucket{tool="read",le="0.5"} 40
claude_bridge_tool_duration_seconds_bucket{tool="read",le="+Inf"} 42
```

### Traces

| Path | Description |
|------|-------------|
| `GET /api/traces` | List recent traces (paginated) |
| `GET /api/traces/stats` | Aggregate trace statistics |

### Events (SSE)

```
GET /api/events
```

Server-Sent Events stream for real-time dashboard updates:

```
event: tool_call
data: {"timestamp":"2026-05-19T10:00:00Z","tool":"read","params":{"filePath":"/src/main.py"}}

event: anomaly
data: {"timestamp":"2026-05-19T10:00:01Z","type":"velocity_high","value":15}
```

---

## Integration

### Prometheus + Grafana

Add a `scrape_configs` entry to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'claude-bridge'
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

Import the Grafana dashboard JSON from `benchmarks/profiles/claude-bridge-dashboard.json`
(or the equivalent in your deployment) for pre-built panels covering:

- Tool call rate and latency percentiles
- Error rate by tool
- Anomaly detection events
- Tracing span volume

### Jaeger

Point `CLAUDE_BRIDGE_OTLP_ENDPOINT` at your Jaeger OTLP collector:

```bash
CLAUDE_BRIDGE_TRACING=detailed \
CLAUDE_BRIDGE_OTLP_ENDPOINT=http://localhost:4317 \
CLAUDE_BRIDGE_OTEL_SERVICE_NAME=claude-bridge \
claude-bridge run --project-dir .
```

Alternatively, use the Jaeger all-in-one Docker container for local development.

---

## Docker Compose (Local Development)

```yaml
version: '3.8'
services:
  claude-bridge:
    image: claude-bridge:latest
    environment:
      CLAUDE_BRIDGE_TRACING: detailed
      CLAUDE_BRIDGE_OTLP_ENDPOINT: http://jaeger:4317
      CLAUDE_BRIDGE_OTEL_SERVICE_NAME: claude-bridge
      CLAUDE_BRIDGE_HEALTH_PORT: '8080'
      CLAUDE_BRIDGE_PROJECT_DIR: /workspace
    volumes:
      - ./workspace:/workspace
    ports:
      - '8080:8080'

  jaeger:
    image: jaegertracing/all-in-one:1.57
    environment:
      COLLECTOR_OTLP_ENABLED: 'true'
    ports:
      - '4317:4317'   # OTLP gRPC
      - '16686:16686' # Jaeger UI

  prometheus:
    image: prom/prometheus:v2.50.0
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - '9090:9090'

  grafana:
    image: grafana/grafana:11.2
    environment:
      GRAFANA_ADMIN_PASSWORD: admin
    ports:
      - '3000:3000'
    volumes:
      - ./grafana-db:/var/lib/grafana
```

---

## Example Prometheus Scrape Config

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'claude-bridge'
    static_configs:
      - targets: ['claude-bridge:8080']
    metrics_path: '/metrics'

  - job_name: 'claude-bridge-traces'
    static_configs:
      - targets: ['jaeger:16686']
    metrics_path: '/metrics'
```