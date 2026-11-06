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

## Sharing boundary

Students and teachers can share a manual notebook or a personal file with a signed-in user, by name or by a link that requires sign-in. A recipient reads current sources and chats in a private thread on their own AI limits, and cannot change sources or see the owner's chats. Revoking applies to the next request. A presigned download URL issued before revocation keeps working until it expires (at most 60 seconds), and an answer already streaming may finish on screen but is not stored. Access beyond this is in scope as IDOR.

## MCP boundary

- **A media link is a bearer capability.** `get_course_media_link` issues a personal link whose token sits in the URL fragment and is stored only hashed. Anyone holding it can open the media for 5 hours without signing in, and an enrolled student or course staff member can always open it. A signed-in person who is not enrolled is refused, but they can sign out and open the same link within the 5 hours: this is accepted, and treating it as a defect is out of scope. The issuer can pass the link on, and an AI app can too.
- **What ends a link.** Asking again replaces the previous link. A link also dies when it is revoked (`DELETE /v1/lms/media/grants/{id}`, or the connectors page), its issuer is blocked or unenrolled, the course is archived, the block is gone, the connector behind it is revoked, or anonymous use passes its ceiling. All of this is checked on each open. If a process cannot check the connector, the link is refused.
- **Presigned URLs outlive revocation briefly.** An open returns a presigned storage URL that lives up to 15 minutes, and revoking does not cancel one already issued.
- **Call log.** Each MCP tool call is logged with redacted arguments and counts, never content. Traces are removed after 90 days. Users see their own calls; administrators' reads are audited.
- **Scope offers.** A new release may offer new scopes for existing student and LMS connectors, never Administration ones. Nothing widens until the owner accepts, from the Telegram buttons or the signed-in connectors page. An offer is single use, lasts 14 days and re-checks the user's status, role and each key at the moment of the grant. Someone else's offer answers the same as an unknown one. The web path needs no step-up code, the same bar as creating a student or LMS connector.

## Safe harbour

We will not pursue or support legal action against you for research that:

- stays within the scope above and makes a good-faith effort to avoid privacy violations, data destruction and service interruption;
- uses only your own accounts or test accounts, and stops and reports as soon as you reach anyone else's data, without keeping, sharing or using it;
- gives us reasonable time to fix the issue before any disclosure.

If in doubt, ask first at the contacts above.

## Security design

The [Security section of the README](README.md#security) summarises the controls: Hydra with PKCE, Vault for EMIS credentials, rate limits, AI access controls and the usage ledger, OpenUI validation, SSRF guards, upload allowlists, SBOM, Trivy and cosign.
