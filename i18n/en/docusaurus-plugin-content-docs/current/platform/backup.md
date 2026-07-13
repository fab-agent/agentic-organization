---
sidebar_position: 7
---

# Backup

You can back up your database at any time to an S3-compatible storage such as AWS S3, Cloudflare R2, or MinIO.

---

## Configuration

Go to **Settings → Backup** and fill in the following fields:

| Field | Description |
|---|---|
| Bucket Name | S3 bucket name (e.g. `my-org-backups`) |
| Prefix | Sub-folder for backup files (default: `backups/`) |
| Endpoint URL | Leave empty for AWS S3. Fill in for Cloudflare R2/MinIO |
| Access Key ID | S3/R2 access key |
| Secret Access Key | Secret key — stored encrypted with AES-256 |
| Region | Region (default: `us-east-1`) |

After saving, the configuration status appears in the card header.

---

## Taking a Backup

Once configured, click **Backup Now**.

The system will:

1. Create an online, consistent copy of the database using the `sqlite3.backup()` API.
2. Name the copy in `app_YYYYMMDD_HHMMSS.db` format.
3. Upload the file to the configured bucket.

Each backup result (success/error, size, timestamp) is automatically recorded in history (last 20 entries).

---

## Supported Storage Providers

| Provider | Endpoint URL |
|---|---|
| AWS S3 | *(leave empty)* |
| Cloudflare R2 | `https://<account_id>.r2.cloudflarestorage.com` |
| MinIO | `http://minio.internal:9000` |
| Wasabi | `https://s3.wasabisys.com` |
| Backblaze B2 | `https://s3.us-west-004.backblazeb2.com` |

---

## Security

- The Secret Access Key is never stored as plain text; it is encrypted with Fernet (AES-256-CBC).
- Backup files are in SQLite format; to restore, simply overwrite the `data/app.db` file.

---

## API

| Endpoint | Description |
|---|---|
| `GET /backup/config` | Returns current configuration (token redacted) |
| `PUT /backup/config` | Saves/updates configuration |
| `DELETE /backup/config` | Deletes all configuration |
| `POST /backup/now` | Triggers an immediate backup |
| `GET /backup/history` | Lists last 20 backup records (newest first) |
