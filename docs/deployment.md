# Kubernetes Deployment Guide

---

## Prerequisites

- Kubernetes 1.28 or later
- Helm 3.15+ (if using the Helm chart)
- `kubectl` configured for the target cluster
- OTLP collector accessible from the cluster (e.g. Grafana Tempo, Jaeger, or a vendor-backed OTLP endpoint)

---

## Helm Chart Installation

```bash
helm repo add claude-bridge https://charts.claude-bridge.dev
helm repo update
helm install claude-bridge claude-bridge/claude-bridge \
  --namespace claude-bridge \
  --create-namespace \
  --values values.yaml
```

### Minimal `values.yaml`

```yaml
image:
  repository: claude-bridge/claude-bridge
  tag: 'latest'
  pullPolicy: IfNotPresent

replicaCount: 1

service:
  type: ClusterIP
  ports:
    health: 8080

env:
  CLAUDE_BRIDGE_TRACING: detailed
  CLAUDE_BRIDGE_OTLP_ENDPOINT: https://otlp.example.com:4317
  CLAUDE_BRIDGE_OTEL_SERVICE_NAME: claude-bridge
  CLAUDE_BRIDGE_PROJECT_DIR: /workspace
  CLAUDE_BRIDGE_AUTO_APPROVE: 'false'

persistence:
  enabled: true
  size: 1Gi
```

---

## Raw Manifests

If Helm is not available, apply the manifests directly:

```bash
kubectl apply -f https://raw.githubusercontent.com/claude-bridge/claude-bridge/main/deploy/k8s/
```

Key manifests:

- `Deployment` — main application replica set
- `Service` — ClusterIP exposing health port
- `ConfigMap` — non-sensitive environment configuration
- `Secret` — OTLP endpoint and other sensitive values
- `HorizontalPodAutoscaler` — optional HPA
- `NetworkPolicy` — optional namespace-scoped network restrictions

---

## Configuration via ConfigMap and Secrets

### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: claude-bridge-config
data:
  CLAUDE_BRIDGE_TRACING: detailed
  CLAUDE_BRIDGE_OTEL_SERVICE_NAME: claude-bridge
  CLAUDE_BRIDGE_PROJECT_DIR: /workspace
  CLAUDE_BRIDGE_APPROVAL_PRESET: dev-safe
```

### Secret (OTLP endpoint)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: claude-bridge-secrets
type: Opaque
stringData:
  CLAUDE_BRIDGE_OTLP_ENDPOINT: https://otlp.example.com:4317
```

Reference in the Deployment:

```yaml
envFrom:
  - configMapRef:
      name: claude-bridge-config
  - secretRef:
      name: claude-bridge-secrets
```

---

## Resource Limits

Set per the workload profile. A baseline for a single-replica setup:

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

Adjust based on tool call volume and shell command complexity.

---

## Horizontal Pod Autoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: claude-bridge-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: claude-bridge
  minReplicas: 1
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
```

---

## Network Policies

Restrict egress to only the OTLP endpoint and required external services:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: claude-bridge-egress
spec:
  podSelector:
    matchLabels:
      app: claude-bridge
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - port: 4317
          protocol: TCP
    - to:
        - namespaceSelector:
            matchLabels:
              name: claude-bridge
      ports:
        - port: 8080
          protocol: TCP
    - ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    - to:
        - namespaceSelector: {}
      ports:
        - port: 443
          protocol: TCP
```

---

## Health Probes

The Deployment includes liveness, readiness, and startup probes by default:

```yaml
livenessProbe:
  httpGet:
    path: /healthz/live
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /healthz/ready
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5

startupProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 10
  failureThreshold: 30
  periodSeconds: 10
```

---

## Production Checklist

- [ ] Set OTLP endpoint secret
- [ ] Configure resource limits
- [ ] Review network policies
- [ ] Set up Prometheus scraping
- [ ] Configure Grafana dashboards

### Additional Hardening

- [ ] Enable Prometheus metrics scraping (`/metrics`)
- [ ] Validate OTLP connectivity from the cluster
- [ ] Set `CLAUDE_BRIDGE_AUTO_APPROVE=false` (default; verify)
- [ ] Mount project volume with `readOnly: true` if the workload is read-only
- [ ] Audit log persistence configured and backed up

---

## Troubleshooting

### Pod not starting

```bash
kubectl describe pod -n claude-bridge -l app=claude-bridge
kubectl logs -n claude-bridge -l app=claude-bridge
```

Check for:
- Missing OTLP endpoint secret
- Incorrect image pull policy
- Volume mount failures

### Health probe failing

```bash
kubectl exec -n claude-bridge deploy/claude-bridge -- wget -qO- http://localhost:8080/healthz
```

If the app starts slowly, increase `initialDelaySeconds` or enable the startup probe.

### Tracing not appearing in Jaeger

1. Verify `CLAUDE_BRIDGE_OTLP_ENDPOINT` is reachable from the pod:
   ```bash
   kubectl exec -n claude-bridge deploy/claude-bridge -- wget -qO- http://<otlp-host>:4317
   ```
2. Check that `CLAUDE_BRIDGE_TRACING` is not set to `none`
3. Inspect trace export errors in app logs:
   ```bash
   kubectl logs -n claude-bridge -l app=claude-bridge | grep -i otlp
   ```

### Metrics not scraping

1. Confirm the Service exposes port `8080`
2. Check Prometheus target health at `http://prometheus:9090/targets`
3. Verify `metrics_path: /metrics` in the scrape config