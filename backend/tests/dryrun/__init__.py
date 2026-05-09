"""Package marker for the opt-in dry-run suite.

This directory is NOT collected by default — ``pytest`` from ``backend/`` runs
``tests/contract`` and ``tests/integration`` only. To run the dry-run suite:

    export LLMOPS_K8S_DRYRUN_KUBECONFIG=/path/to/scratch-kubeconfig
    pytest tests/dryrun/

Every test here is additionally gated at runtime via ``pytest.skip`` so even if
it is collected, nothing runs unless the env var is set. See the Testing
Policy in ``.cursor/rules/specify-rules.mdc``.
"""
