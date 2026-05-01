"""Generate Kubernetes manifests for CPU-only text generation inference.

Returns a single multi-document YAML string containing:

1. ``Secret`` holding the HF token (mounted as env var ``HF_TOKEN``).
2. ``Deployment`` running Hugging Face Text Generation Inference (TGI) on CPU.
3. ``Service`` of type ``LoadBalancer`` exposing port 80 → container :8000.

The service remains exposed via a public LoadBalancer endpoint and the backend
inference proxy adapts the TGI response into the existing OpenAI-style shape
expected by the frontend.
"""
from __future__ import annotations

import re

import yaml

# Pin to a known-good CPU tag. ``latest`` drift previously pulled an image
# whose bundled dependencies (compressed_tensors/transformers) were incompatible
# and caused ShardCannotStart at import-time.
_IMAGE = "ghcr.io/huggingface/text-generation-inference:3.3.6-intel-cpu"
_CONTAINER_PORT = 8000
_SERVICE_PORT = 80


def _safe_name(hf_model_id: str) -> str:
    """Turn ``Qwen/Qwen3-1.7B`` into ``qwen-qwen3-1-7b`` so it is a valid k8s name."""
    lower = hf_model_id.lower()
    cleaned = re.sub(r"[^a-z0-9-]+", "-", lower).strip("-")
    cleaned = re.sub(r"-+", "-", cleaned)
    return cleaned[:50] or "inference"


def generate(
    *,
    hf_model_id: str,
    hf_token: str,
    cluster_name: str,
    namespace: str = "default",
) -> str:
    """Return a multi-document YAML string with Secret + Deployment + Service."""
    name = _safe_name(hf_model_id)
    secret_name = f"{name}-hf-token"
    deployment_name = f"{name}-inference"
    service_name = f"{name}-svc"

    common_labels = {
        "app.kubernetes.io/name": name,
        "app.kubernetes.io/component": "tgi-cpu",
        "app.kubernetes.io/managed-by": "llmops-platform",
        "llmops.cluster": cluster_name,
    }

    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": secret_name,
            "namespace": namespace,
            "labels": common_labels,
        },
        "stringData": {
            "HF_TOKEN": hf_token,
        },
    }

    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": deployment_name,
            "namespace": namespace,
            "labels": common_labels,
        },
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app.kubernetes.io/name": name}},
            "template": {
                "metadata": {"labels": common_labels},
                "spec": {
                    "containers": [
                        {
                            "name": "tgi",
                            "image": _IMAGE,
                            "imagePullPolicy": "IfNotPresent",
                            "args": [
                                "--model-id",
                                hf_model_id,
                                "--port",
                                str(_CONTAINER_PORT),
                                "--hostname",
                                "0.0.0.0",
                                "--dtype",
                                "bfloat16",
                                "--max-input-length",
                                "4096",
                                "--max-total-tokens",
                                "6144",
                                "--max-concurrent-requests",
                                "16",
                                "--max-batch-prefill-tokens",
                                "2048",
                                "--disable-custom-kernels",
                            ],
                            "env": [
                                {
                                    "name": "HF_TOKEN",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": secret_name,
                                            "key": "HF_TOKEN",
                                        }
                                    },
                                },
                                {
                                    "name": "HUGGING_FACE_HUB_TOKEN",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": secret_name,
                                            "key": "HF_TOKEN",
                                        }
                                    },
                                },
                            ],
                            "ports": [{"containerPort": _CONTAINER_PORT}],
                            "resources": {
                                "limits": {
                                    "memory": "4Gi",
                                    "cpu": "1",
                                    "ephemeral-storage": "8Gi",
                                },
                                "requests": {
                                    "memory": "2Gi",
                                    "cpu": "500m",
                                    "ephemeral-storage": "6Gi",
                                },
                            },
                            "startupProbe": {
                                "httpGet": {"path": "/health", "port": _CONTAINER_PORT},
                                "initialDelaySeconds": 30,
                                "periodSeconds": 10,
                                "timeoutSeconds": 5,
                                "failureThreshold": 90,
                            },
                            "readinessProbe": {
                                "httpGet": {"path": "/health", "port": _CONTAINER_PORT},
                                "initialDelaySeconds": 30,
                                "periodSeconds": 10,
                                "timeoutSeconds": 5,
                                "failureThreshold": 20,
                            },
                            "livenessProbe": {
                                "httpGet": {"path": "/health", "port": _CONTAINER_PORT},
                                "initialDelaySeconds": 30,
                                "periodSeconds": 30,
                                "timeoutSeconds": 5,
                                "failureThreshold": 10,
                            },
                        }
                    ],
                    "terminationGracePeriodSeconds": 30,
                },
            },
        },
    }

    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": service_name,
            "namespace": namespace,
            "labels": common_labels,
        },
        "spec": {
            "type": "LoadBalancer",
            "selector": {"app.kubernetes.io/name": name},
            "ports": [
                {
                    "name": "http",
                    "port": _SERVICE_PORT,
                    "targetPort": _CONTAINER_PORT,
                    "protocol": "TCP",
                }
            ],
        },
    }

    return yaml.safe_dump_all([secret, deployment, service], sort_keys=False)


__all__ = ["generate"]