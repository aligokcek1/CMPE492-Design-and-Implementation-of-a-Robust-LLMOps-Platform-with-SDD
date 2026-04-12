# Data Model: Session Persistence and Continuity

## Entities

### `AuthSession`

Represents one authenticated platform session tied to one device/browser scope.

- `session_token` (string): Opaque token issued by backend, used by client on protected API calls.
- `username` (string): Authenticated Hugging Face username.
- `hf_token` (string): User HF token retained server-side only (never returned in API responses).
- `device_scope` (string): Stable per-device/browser identifier used for session scoping.
- `issued_at` (datetime): Session creation timestamp.
- `last_seen_at` (datetime): Most recent authenticated activity timestamp.
- `expires_at` (datetime): Sliding inactivity expiration timestamp (`last_seen_at + 24h`).
- `status` (enum): `active | expired | revoked`.

**Validation rules**:
- `session_token` MUST be unique.
- `expires_at` MUST advance on each successful authenticated request.
- Session MUST transition to `expired` when `now > expires_at`.
- Revoked sessions MUST fail all future auth checks.

---

### `SessionValidationResult`

Result returned by session-check and auth dependency resolution.

- `username` (string)
- `session_token` (string)
- `expires_at` (datetime)
- `status` (enum): `active | expired | revoked | missing`

**Validation rules**:
- Only `active` result is accepted for protected operations.
- `expired`, `revoked`, and `missing` map to unauthorized responses with actionable error detail.

---

### `OperationReceipt`

Tracks accepted side-effect operations for idempotent retry behavior.

- `operation_type` (enum): `upload | deploy`
- `idempotency_key` (string): Client-provided key for dedupe.
- `session_token` (string): Session that initiated the operation.
- `request_fingerprint` (string): Deterministic digest of relevant request payload.
- `accepted_at` (datetime): Operation acceptance time.
- `result_status` (enum): `accepted | success | failed`
- `result_payload` (object): Serialized API response body to replay on duplicate retry.

**Validation rules**:
- `idempotency_key` MUST map to a single `request_fingerprint`.
- Repeated request with same key + same fingerprint MUST replay existing response.
- Repeated request with same key + different fingerprint MUST fail validation (conflict).

---

### `ReAuthenticationContext` *(frontend session state)*

Captures UI continuity information during session expiry and re-login.

- `selected_tab` (string): Active app tab at expiry time.
- `selected_model` (string | null): Current selected model identifier if any.
- `pending_action_type` (enum): `none | upload | deploy | list_models | fetch_public_info`
- `pending_action_payload` (object | null): Safe replay payload for non-destructive retry flow.
- `last_auth_error` (string | null): Most recent auth-related UI message.

**Validation rules**:
- Must never store raw HF token after successful session issue.
- `pending_action_payload` may be retained only until re-login outcome is resolved.

---

## State Transitions

### Session Lifecycle

```text
           verify token success
 [unauthenticated] -----------------> [active]
                                         |
                                         | authenticated request
                                         | (slide expiration)
                                         v
                                      [active]
                                         |
                    inactivity > 24h      | logout
                                         |
                                         v
                                    [expired] <---- [revoked]
```

### Protected Operation with Expiry

```text
[request received + session active]
            |
            v
   [operation accepted]
            |
            | session expires/revokes later
            v
[operation continues to terminal state]
            |
            v
[result visible after re-authentication]
```

### Idempotent Retry

```text
first request (key K) ---> execute + store receipt
retry request (key K, same payload) ---> return stored receipt
retry request (key K, different payload) ---> conflict error
```
