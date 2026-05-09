"""T018 — Fernet round-trip integration test.

This test goes through real SQLite (the `temp_db` fixture writes a fresh file
into `tmp_path` per test) and verifies:

  1. The `service_account_json_encrypted` BLOB column on `gcp_credentials` does
     NOT contain the plaintext JSON.
  2. Running the decrypt helper returns the exact original JSON.

If Fernet encryption were accidentally disabled or replaced with a passthrough
shim, this test fails loudly — which matters because the stored blob is the
only place a user's GCP SA key lives at rest.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select


def _sample_sa_json() -> str:
    return json.dumps({
        "type": "service_account",
        "project_id": "secret-proj-12345",
        "private_key_id": "kid",
        "private_key": "-----BEGIN PRIVATE KEY-----\nTOPSECRET\n-----END PRIVATE KEY-----\n",
        "client_email": "sa@secret-proj-12345.iam.gserviceaccount.com",
    })


@pytest.mark.asyncio
async def test_sa_json_stored_encrypted_and_round_trips(temp_db, fake_gcp_provider):
    from src.db import get_session_factory
    from src.db.models import GCPCredentialsRow
    from src.services.credentials_store import credentials_store
    from src.services.crypto import decrypt

    sa_json = _sample_sa_json()
    billing = "billingAccounts/TOPSEC-012345-ABCDEF"

    await credentials_store.save(
        user_id="alice",
        sa_json=sa_json,
        billing_account_id=billing,
        provider=fake_gcp_provider,
    )

    session_factory = get_session_factory()
    with session_factory() as db:
        row = db.execute(select(GCPCredentialsRow).where(GCPCredentialsRow.user_id == "alice")).scalar_one()

        stored_blob: bytes = row.service_account_json_encrypted
        assert isinstance(stored_blob, bytes)
        assert b"BEGIN PRIVATE KEY" not in stored_blob
        assert b"secret-proj-12345" not in stored_blob
        assert b"sa@secret-proj-12345" not in stored_blob

        assert decrypt(stored_blob) == sa_json
