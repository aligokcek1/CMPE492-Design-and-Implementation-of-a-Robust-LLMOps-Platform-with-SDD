"""T014 — `NEVER_IMPORT_REAL_GCP_IN_TESTS` guard.

The testing policy (.cursor/rules/specify-rules.mdc) requires that *no* pytest
run imports the real `google.cloud.*` clients used to talk to GCP. All tests
MUST go through `FakeGCPProvider`. This test asserts that invariant by:

1. Verifying the fake-provider env flag is active (`LLMOPS_USE_FAKE_GCP=1`).
2. Verifying that the real GCP client modules are not present in `sys.modules`
   at the point this test runs. If they are, some production-code path has
   pulled them in, likely because a module-level `import` snuck past the DI
   boundary.

Any failure here should be treated as CRITICAL — a future test could silently
start billing a real GCP account.
"""
from __future__ import annotations

import os
import sys


_FORBIDDEN_PREFIXES = (
    "google.cloud.resourcemanager",
    "google.cloud.resource_manager",
    "google.cloud.billing",
    "google.cloud.container",
)


def test_fake_gcp_flag_is_set() -> None:
    assert os.environ.get("LLMOPS_USE_FAKE_GCP") == "1", (
        "Tests must run with LLMOPS_USE_FAKE_GCP=1; see backend/tests/contract/conftest.py."
    )


def test_no_real_gcp_modules_loaded() -> None:
    leaked = sorted(
        name for name in sys.modules if any(name.startswith(p) for p in _FORBIDDEN_PREFIXES)
    )
    assert not leaked, (
        "Real GCP client modules were imported during the test run: "
        f"{leaked}. Tests must only interact with GCP via FakeGCPProvider."
    )


def test_main_app_importable_without_loading_real_gcp() -> None:
    import src.main as main  # noqa: F401 - we only care about import side-effects

    leaked = sorted(
        name for name in sys.modules if any(name.startswith(p) for p in _FORBIDDEN_PREFIXES)
    )
    assert not leaked, (
        "Importing src.main pulled in real GCP modules: "
        f"{leaked}. Lazy-import them inside RealGCPProvider instead."
    )
