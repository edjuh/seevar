# 🧬 AAVSO LOGIC & AUTHENTICATION (S30-PRO)

> **Objective**: Define the authenticated handshake for the AAVSO VSP API.
> **Scope**: Universal (Reusable for any $USER with valid credentials).

## 1. Authentication Requirements
The system requires three keys defined in the local `config.toml` under the `[aavso]` block. These must NOT be committed to version control.

| Config Key | API Header | Purpose |
| :--- | :--- | :--- |
| `observer_code` | `X-Observer-Code` | Unique AAVSO Observer Identifier |
| `target_key` | `X-Target-Key` | VSP API Access Key |
| `webobs_token` | `Authorization: Bearer` | Session Token for WebObs/API |

## 2. Verified Infrastructure
- **Canonical Host**: `apps.aavso.org` (Direct access to API engine).
- **Endpoint**: `/vsp/api/chart/`.
- **Method**: `GET`.

## 3. Implementation Protocol
To prevent 401/404 errors during (re)-installation:
1. Use `apps.aavso.org` to avoid redirect header stripping.
2. Pass `star` as a URL-encoded parameter.
3. Apply `fov=60` and `maglimit=15.0` as baseline S30-PRO defaults.
4. **Pi-Sleep**: A mandatory 188.4s delay between requests to respect AAVSO bandwidth.

## 4. Troubleshooting
- **"No Chart matches"**: Check naming convention in `targets.json` (use `name` key).
- **"Unauthorized"**: Verify `target_key` and `webobs_token` in `config.toml`.
