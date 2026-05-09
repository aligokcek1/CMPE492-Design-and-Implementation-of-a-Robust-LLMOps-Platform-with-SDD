"""T032 — vLLM manifest snapshot test.

Validates that ``vllm_manifest.generate(...)`` produces the expected
Kubernetes resources (``Deployment + Service + Secret``) with the correct
shape and key fields. This is a structural check — the opt-in dry-run suite
(T033, in ``tests/dryrun/``) performs the real server-side validation via
``dry_run=["All"]`` against a scratch kubeconfig.
"""
from __future__ import annotations

import yaml


def _load_docs(manifest_yaml: str) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(manifest_yaml) if doc is not None]


def test_vllm_manifest_generates_deployment_service_secret():
    from src.services.vllm_manifest import generate

    manifest_yaml = generate(
        hf_model_id="Qwen/Qwen3-1.7B",
        hf_token="hf_fake_token",
        cluster_name="llmops-cluster",
    )

    docs = _load_docs(manifest_yaml)
    kinds = [d["kind"] for d in docs]
    assert "Deployment" in kinds
    assert "Service" in kinds
    assert "Secret" in kinds


def test_vllm_manifest_deployment_is_cpu_only():
    from src.services.vllm_manifest import generate

    manifest_yaml = generate(
        hf_model_id="Qwen/Qwen3-1.7B",
        hf_token="hf_fake_token",
        cluster_name="llmops-cluster",
    )

    deployment = next(d for d in _load_docs(manifest_yaml) if d["kind"] == "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]

    resources = container["resources"]
    assert "nvidia.com/gpu" not in resources["limits"]
    assert "nvidia.com/gpu" not in resources["requests"]
    assert "nodeSelector" not in deployment["spec"]["template"]["spec"]

    assert "text-generation-inference:3.3.6-intel-cpu" in container["image"]
    # Model id is passed as a CLI arg, not baked into the image.
    combined_args = " ".join(container.get("args", []))
    assert "--model-id" in combined_args
    assert container["args"].count("--disable-custom-kernels") == 1
    assert "Qwen/Qwen3-1.7B" in combined_args
    assert resources["requests"]["ephemeral-storage"] == "6Gi"
    assert resources["limits"]["ephemeral-storage"] == "8Gi"
    assert "startupProbe" in container
    assert container["startupProbe"]["failureThreshold"] == 90
    assert container["readinessProbe"]["failureThreshold"] == 20
    assert container["livenessProbe"]["failureThreshold"] == 10


def test_vllm_manifest_service_is_loadbalancer_port_80():
    from src.services.vllm_manifest import generate

    manifest_yaml = generate(
        hf_model_id="Qwen/Qwen3-1.7B",
        hf_token="hf_fake_token",
        cluster_name="llmops-cluster",
    )

    service = next(d for d in _load_docs(manifest_yaml) if d["kind"] == "Service")
    assert service["spec"]["type"] == "LoadBalancer"

    ports = service["spec"]["ports"]
    assert any(p["port"] == 80 and p["targetPort"] == 8000 for p in ports)


def test_vllm_manifest_embeds_hf_token_as_secret_reference():
    from src.services.vllm_manifest import generate

    manifest_yaml = generate(
        hf_model_id="Qwen/Qwen3-1.7B",
        hf_token="hf_actual_secret_value_here",
        cluster_name="llmops-cluster",
    )
    docs = _load_docs(manifest_yaml)

    # The HF token MUST be in the Secret, not splashed across env blocks elsewhere.
    secret = next(d for d in docs if d["kind"] == "Secret")
    assert "hf-token" in secret["metadata"]["name"].lower()

    deployment = next(d for d in docs if d["kind"] == "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = container.get("env") or []
    hf_env = next(e for e in env if e["name"] in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"))
    assert "valueFrom" in hf_env
    assert hf_env["valueFrom"]["secretKeyRef"]["name"] == secret["metadata"]["name"]

    # Plaintext should NOT appear anywhere in the Deployment doc
    assert "hf_actual_secret_value_here" not in yaml.safe_dump(deployment)
