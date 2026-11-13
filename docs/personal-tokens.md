# Personal tokens

A personal token lets a script or an AI client call your own data without an interactive sign-in. It acts as you, so treat it like a password.

## Properties

| | |
|---|---|
| Format | `ihsp_pat_` followed by 256 random bits. Only a SHA-256 hash is stored. |
| Shown | Once, in the response that creates it. |
| Scopes | `me:read` (GET and HEAD) and `me:write` (every other method). |
| Reach | Only `/v1/me` and `/v1/me/*`. Any other path answers `403` with code `id/token-scope`. |
| Lifetime | `expires_in_days` is 30, 90 or 365. |
| Name | 1 to 80 characters. |
| Creation | Needs a one-time code (step-up) sent to your Telegram or, as a fallback, your email. |

A request is authorised when the token is not revoked and not expired, and the scope matching the method is on the token.

## Create a token

Sign in to get an access token (`$ACCESS`), then ask for a code. The response is `202` with no body.

```bash
curl -X POST https://api.example.org/v1/id/me/step-up \
  -H "Authorization: Bearer $ACCESS"
```

Enter the code you received:

```bash
curl -X POST https://api.example.org/v1/id/personal-tokens \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -d '{"name": "laptop script", "scopes": ["me:read"], "expires_in_days": 90, "otp_code": "123456"}'
```

The answer is `201`:

```json
{
  "personal_token": {
    "id": "0192f0e8-0000-7000-8000-000000000000",
    "name": "laptop script",
    "prefix": "k3J9xQ2a",
    "scopes": ["me:read"],
    "created_at": "2026-11-13T09:00:00Z",
    "expires_at": "2027-02-11T09:00:00Z",
    "last_used_at": null,
    "revoked_at": null
  },
  "token": "ihsp_pat_..."
}
```

Without `otp_code` the call fails with a second-factor-required error; a wrong code fails the check.

## Use a token

```bash
curl https://api.example.org/v1/me \
  -H "Authorization: Bearer ihsp_pat_..."
```

## List and revoke

```bash
curl https://api.example.org/v1/id/personal-tokens -H "Authorization: Bearer $ACCESS"

curl -X DELETE https://api.example.org/v1/id/personal-tokens/$TOKEN_ID \
  -H "Authorization: Bearer $ACCESS"
```

Listing is newest first and includes revoked tokens; it never returns the secret. Revoking answers `204`, works at once, and repeating it changes nothing. A token id that is not yours answers `404`. Creation and revocation are written to your activity log.

## AI clients (MCP)

AI services such as ChatGPT, Gemini and Claude connect to the platform's MCP servers with OAuth. Where a service accepts a static header instead (Claude custom connectors, custom clients), create a connector token on the connectors page (`POST /v1/id/me/connectors`, also confirmed with a step-up code). Connector tokens carry MCP scopes and may be limited to courses; personal tokens above are for the `/v1/me/*` API only. Vendor guides:

- [ChatGPT developer mode and MCP apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)
- [Gemini](https://support.google.com/gemini/answer/17209137)
- [Claude custom connectors](https://claude.com/docs/connectors/custom/remote-mcp)
