# Nulm Helm Chart

Local-first MCP agent quality and execution layer.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+

## Installation

```bash
helm repo add nulm https://3keggo3-hash.github.io/nulm
helm install nulm nulm/nulm
```

Or from source:

```bash
cd helm/nulm
helm install nulm .
```

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of replicas | `2` |
| `image.repository` | Container image repository | `nulm/nulm` |
| `image.tag` | Container image tag | `latest` |
| `service.type` | Service type | `ClusterIP` |
| `service.ports.dashboard` | Dashboard port | `8765` |
| `service.ports.health` | Health check port | `8766` |
| `autoscaling.enabled` | Enable HPA | `true` |
| `autoscaling.minReplicas` | Minimum replicas | `2` |
| `autoscaling.maxReplicas` | Maximum replicas | `10` |
| `autoscaling.targetCPUUtilizationPercentage` | CPU target for HPA | `70` |

## Secret Configuration

Secrets require base64-encoded values. Edit the secret after installation:

```bash
kubectl edit secret nulm-secret
```

Or provide via values:

```yaml
secret:
  otlpEndpoint: "your-base64-encoded-endpoint"
  aiEvaluatorApiKey: "your-base64-encoded-key"
```

## Accessing the Dashboard

```bash
kubectl port-forward svc/nulm 8765:8765
```

Then open http://localhost:8765

## Upgrading

```bash
helm upgrade nulm nulm/nulm
```

## Uninstalling

```bash
helm uninstall nulm
```