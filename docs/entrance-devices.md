# Entrance devices

An entrance device is a camera at the school door. It sends a photo, the backend recognises the student against the faces on file and records the passage. Devices are not users: they authenticate with their own token.

## Administrator routes

All need an administrator's access token (`$ACCESS`).

| Method and path | Purpose |
|---|---|
| `GET /v1/admin/devices` | Every device, newest first. |
| `POST /v1/admin/devices` | Create a device (`201`). |
| `POST /v1/admin/devices/{device_id}/revoke` | Stop the token from working. |
| `GET /v1/admin/devices/{device_id}/calls` | The device's requests of the last 7 days. |

### Create

```bash
curl -X POST https://api.example.org/v1/admin/devices \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -d '{"name": "Main entrance"}'
```

`name` is 1 to 200 characters in the schema (a trimmed name longer than 80 is refused with `faces/device-name`).

```json
{
  "id": "0192f0e8-0000-7000-8000-000000000000",
  "name": "Main entrance",
  "key_prefix": "a1b2c3d4",
  "created_at": "2026-11-13T09:00:00Z",
  "token": "ihsp_dev_..."
}
```

The `token` (`ihsp_dev_` plus 256 random bits) appears only in this response; only its hash is stored. List responses show `key_prefix`, `created_at`, `revoked_at` and `last_used_at`.

### Revoke and inspect

```bash
curl -X POST https://api.example.org/v1/admin/devices/$DEVICE_ID/revoke \
  -H "Authorization: Bearer $ACCESS"

curl https://api.example.org/v1/admin/devices/$DEVICE_ID/calls \
  -H "Authorization: Bearer $ACCESS"
```

Each call has `at`, `status` (`matched`, `no_match`, `no_face`, `multiple_faces`), `matched_user_id`, `matched_name` and `excused`. Calls are kept for 7 days.

## Device route: identify

`POST /v1/device/identify` takes `multipart/form-data` and the device token as a Bearer token.

| Field | Meaning |
|---|---|
| `file` | A JPEG or PNG, at most 5 MiB, with one face. |
| `direction` | `in` or `out`. |

```bash
curl -X POST https://api.example.org/v1/device/identify \
  -H "Authorization: Bearer ihsp_dev_..." \
  -F "direction=in" \
  -F "file=@door.jpg;type=image/jpeg"
```

Recognised:

```json
{
  "student": {"id": "0192f0e8-1111-7000-8000-000000000000", "full_name": "Student Name", "group": "10-A"},
  "excused": false,
  "excuse_until": null
}
```

Nobody recognised (no face, several faces or no match) is still `200`: `student` is `null`, `excused` is `false`. `excused` is true while the student has an active excuse, with `excuse_until` the date it ends. A recognised passage is stored with its direction, and an exit may notify the student's contacts.

## Errors

- `401` `faces/device-unauthorized`: missing, malformed, unknown or revoked token.
- Image problems answer validation errors: `faces/image-empty`, `faces/image-too-large`, `faces/image-type`.
- A device is rate limited per minute; excess requests are refused.
- `404` `faces/device-not-found` on an unknown device id in the administrator routes.

## Faces on file

Students enrol their own face at `PUT /v1/me/face`; a curator or administrator can set one with `PUT /v1/staff/students/{student_id}/face`, which locks it against student changes.
