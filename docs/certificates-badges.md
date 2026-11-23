# Course certificates, partners and badges

## Certificates

Course staff design a certificate per course. Routes are under `/v1/certificates/courses/{course_id}`:

| Route | Purpose |
|---|---|
| `GET`, `PUT /settings` | pass mark, honors tiers and issuing rules |
| `GET`, `POST /templates`; `PUT`, `DELETE /templates/{template_id}` | certificate designs |
| `POST /templates/{template_id}/background` | upload a background |
| `GET /templates/{template_id}/preview.png`, `GET /sample.png` | previews |
| `GET`, `POST /partners`; `PUT`, `DELETE /partners/{partner_id}` | course partners; `POST /partners/{partner_id}/logo` uploads a logo |
| `GET /issued` | issued certificates |
| `POST /issue-eligible` | issue to everyone who passed |
| `POST /issued/{cert_id}/revoke` | revoke |
| `POST /mine` | a learner claims their certificate |
| `GET /issued/{cert_id}/pdf` | the PDF |
| `GET /public` | public course certificate info |

Each certificate has a verify URL and QR code: `GET /v1/certificates/verify/{code}` and `/v1/certificates/verify/{code}/qr.svg`. Honors tiers are set from the pass mark settings.

## Badges

Badges are per course. Under `/v1/lms`: `GET`, `POST /courses/{course_id}/badges`, `PUT`, `DELETE /courses/{course_id}/badges/{badge_id}`, `POST .../image`, `PUT /courses/{course_id}/badge-settings`. Learners read `GET /badges/mine` and mark an award seen with `POST /badges/awards/{award_id}/seen`; `GET /users/{user_id}/badges` lists a user's badges. A badge is awarded by a rule assembled from blocks in the rule builder.

The exact shapes are in `openapi/openapi.json`.
