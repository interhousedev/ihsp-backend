# Security policy

IHSP handles minors' school records, EMIS credentials and staff accounts. We take every report seriously and thank everyone who reports responsibly.

## Supported versions

| Version | Supported |
|---|---|
| The latest release (`vX.Y.Z` tag) and `main` | Yes |
| The previous minor release | Critical fixes only, for 30 days after the next minor release |
| Anything older | No |

Releases are container images `ghcr.io/interhousedev/ihsp-backend:<version>`, signed with keyless cosign (see [README.md](README.md#deployment) for the verification command).

## Reporting a vulnerability

**Never open a public issue, discussion or pull request for a vulnerability.**

1. Preferred: open a private report through [GitHub Security Advisories](https://github.com/interhousedev/ihsp-backend/security/advisories/new).
2. Or write to **alex@sayfi.uz**, or on Telegram to **@megaplov**.

Please include the affected component (process, route, bot command or module), the version or commit, the steps to reproduce, the impact you see, and whether you have shared the finding with anyone else. Do not send real student data; describe it instead.

## Response targets

| Step | Target |
|---|---|
| Acknowledgement | 2 business days |
| First assessment and severity (CVSS 3.1) | 5 business days |
| Fix or mitigation for critical and high | 14 days |
| Fix for medium and low | the next regular release, at most 90 days |
| Public advisory and credit | after a fixed release is deployed, coordinated with you |

The school week is Monday to Friday, Tashkent time (UTC+5). We keep you informed at least weekly until the issue is closed.

## Scope

In scope:

- This repository: the backend processes (`identity`, `api`, `bot`, `mail`, `worker`, `scheduler`, `migrate`), the MCP servers, the compose files, the nginx, Hydra and Vault configuration, and the deployment scripts.
- Authentication and authorization: OAuth/PKCE flows, the token handler, passkeys, role and scope checks, IDOR between students, groups, courses or notebooks, guest and revoked-user access.
- AI features: prompt injection that leads to data disclosure or to a data-changing tool call without approval, bypass of AI access revocation or limits, unsafe OpenUI output.
- SSRF, upload validation, rate limit bypass, account enumeration, secret leakage, supply-chain issues in the build.

Out of scope:

- The production instance at `ihsu.uz` beyond what is needed to show an issue with the code. No load or denial-of-service testing, no automated scanning, no social engineering, no physical attacks.
- Third-party services (EMIS, OpenRouter, Exa, Telegram) themselves; report those to their owners.
- Model output quality or a jailbreak that has no security impact.
- Findings that need a compromised server, a leaked administrator session or development-only settings (`materials/dev.env`, fake modes).
- Missing hardening headers or best practices without a demonstrated impact.

## Safe harbour

We will not pursue or support legal action against you for research that:

- stays within the scope above and makes a good-faith effort to avoid privacy violations, data destruction and service interruption;
- uses only your own accounts or test accounts, and stops and reports as soon as you reach anyone else's data, without keeping, sharing or using it;
- gives us reasonable time to fix the issue before any disclosure.

If in doubt, ask first at the contacts above.

## Security design

The [Security section of the README](README.md#security) summarises the controls: Hydra with PKCE, Vault for EMIS credentials, rate limits, AI access controls and the usage ledger, OpenUI validation, SSRF guards, upload allowlists, SBOM, Trivy and cosign.
