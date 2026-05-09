"""T033 — Opt-in Kubernetes server-side dry-run for the vLLM manifest.

Runs only when ``LLMOPS_K8S_DRYRUN_KUBECONFIG`` points at a real (scratch)
kubeconfig. Uses ``kubernetes.client`` with ``dry_run=["All"]`` so nothing
is actually created on the cluster — the API server performs admission +
validation and returns the object it *would* have persisted. Zero GCP calls,
zero cloud side-effects.
"""
from __future__ import annotations

import os

import pytest
import yaml


def _require_kubeconfig() -> str:
    kubeconfig = os.environ.get("LLMOPS_K8S_DRYRUN_KUBECONFIG")
    if not kubeconfig:
        pytest.skip("LLMOPS_K8S_DRYRUN_KUBECONFIG not set; opt-in dry-run suite skipped.")
    if not os.path.exists(kubeconfig):
        pytest.skip(f"Kubeconfig {kubeconfig} does not exist.")
    return kubeconfig


def test_vllm_manifest_applies_server_side_dry_run():
    kubeconfig = _require_kubeconfig()

    from kubernetes import client, config

    from src.services.vllm_manifest import generate

    config.load_kube_config(config_file=kubeconfig)

    manifest_yaml = generate(
        hf_model_id="Qwen/Qwen3-0.6B",
        hf_token="hf_scratch_token_dryrun_only",
        cluster_name="llmops-cluster",
    )
    docs = [d for d in yaml.safe_load_all(manifest_yaml) if d is not None]

    apps_v1 = client.AppsV1Api()
    core_v1 = client.CoreV1Api()
    ns = "default"

    for doc in docs:
        kind = doc["kind"]
        if kind == "Deployment":
            apps_v1.create_namespaced_deployment(
                namespace=ns, body=doc, dry_run="All"
            )
        elif kind == "Service":
            core_v1.create_namespaced_service(
                namespace=ns, body=doc, dry_run="All"
            )
        elif kind == "Secret":
            core_v1.create_namespaced_secret(
                namespace=ns, body=doc, dry_run="All"
            )
        else:
            pytest.fail(f"Unexpected manifest kind: {kind}")
