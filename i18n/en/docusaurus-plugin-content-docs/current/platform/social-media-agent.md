---
sidebar_position: 8
---

# Social Media Agent Skills

The platform provides two built-in skills for adding Instagram and WhatsApp capabilities to agents:

- `instagram_post` — Publish a photo + caption to an Instagram Business account
- `whatsapp_send` — Send a text message via WhatsApp Business Cloud API

---

## Prerequisites

### Instagram

- An **Instagram Business** or **Creator** account
- A **Facebook Page** connected to the account
- Permissions added to your Meta App: `instagram_basic`, `instagram_content_publish`
- A **Page Access Token** obtained via [Meta Graph API Explorer](https://developers.facebook.com/tools/explorer/) (use a long-lived token for permanent access)
- The account's **IG Business User ID**

### WhatsApp

- A **WhatsApp Business** account (via Meta Business Suite)
- Permission added to your Meta App: `whatsapp_business_messaging`
- **Phone Number ID** (Meta Business Dashboard → WhatsApp → Getting Started)
- **System User Access Token** (Business Settings → System Users)

> **Note:** WhatsApp Status (Stories) is not supported by the official Cloud API. This skill sends text messages to the specified number.

---

## Configuration

1. Go to **Settings → Social Media**.
2. In the Instagram section, enter your **IG Business User ID** and **Access Token**.
3. In the WhatsApp section, enter your **Phone Number ID**, **Access Token**, and optionally a **Default Recipient** (E.164 format, e.g. `+15551234567`).
4. Click **Save**. Credentials are stored encrypted with AES-256.

---

## Adding Skills to an Agent

1. Click on an agent in the **Personnel** list.
2. Go to the **Agent Configuration** section.
3. Click **Add Skill** → select **Skill type: builtin**.

| Skill Name | Type | Description |
|---|---|---|
| `instagram_post` | builtin | Instagram post with photo + caption |
| `whatsapp_send` | builtin | Send a WhatsApp message |

### instagram_post parameters

| Parameter | Required | Description |
|---|---|---|
| `image_url` | ✅ | A publicly accessible image URL (HTTPS) |
| `caption` | ✅ | Post description (including hashtags) |

### whatsapp_send parameters

| Parameter | Required | Description |
|---|---|---|
| `message` | ✅ | Text to send |
| `to` | ❌ | Recipient number (E.164). If omitted, uses the default recipient |

---

## Example Usage

During a chat with the agent:

```
You: Share an Instagram post for today's campaign:
     Image: https://cdn.example.com/promo.jpg
     Caption: Our new season collection is here! 🚀 #fabrika #software

Agent: [instagram_post call] → ✅ Published to Instagram — media ID: 17900000000000000
```

```
You: Send the project update to +15551234567: "Sprint 4 complete, test environment is ready."

Agent: [whatsapp_send call] → ✅ WhatsApp message sent → +15551234567
```

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /social-media/config` | Returns current configuration |
| `PUT /social-media/config` | Saves/updates configuration |
| `DELETE /social-media/config` | Deletes all credentials |
| `POST /social-media/instagram/post` | Directly creates an Instagram post |
| `POST /social-media/whatsapp/send` | Directly sends a WhatsApp message |
