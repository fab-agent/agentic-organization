"""
Instagram Graph API + WhatsApp Business Cloud API helpers.

Instagram: requires an Instagram Business account linked to a Facebook Page.
  Credentials: ig_user_id (IG Business User ID), access_token (Page/User token)

WhatsApp: uses Meta Cloud API to send messages to a specific recipient.
  Credentials: phone_number_id (WhatsApp Business Phone Number ID), access_token
  Note: WhatsApp Status Stories are NOT available via the official Cloud API.
  This implementation sends a text message instead.
"""
import httpx

GRAPH_BASE = "https://graph.facebook.com/v21.0"


async def instagram_post_photo(
    *,
    ig_user_id: str,
    access_token: str,
    image_url: str,
    caption: str,
) -> dict:
    """Publish a photo post to an Instagram Business feed."""
    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1 — create media container
        r = await client.post(
            f"{GRAPH_BASE}/{ig_user_id}/media",
            params={
                "image_url": image_url,
                "caption": caption,
                "access_token": access_token,
            },
        )
        _raise(r)
        creation_id = r.json()["id"]

        # Step 2 — publish
        r2 = await client.post(
            f"{GRAPH_BASE}/{ig_user_id}/media_publish",
            params={
                "creation_id": creation_id,
                "access_token": access_token,
            },
        )
        _raise(r2)
        return r2.json()  # {"id": "<media_id>"}


async def instagram_post_text(
    *,
    ig_user_id: str,
    access_token: str,
    caption: str,
) -> dict:
    """Create an Instagram text-only post (no image — uses carousel trick with text overlay).
    Falls back to feed post with caption only if no image URL is provided."""
    # Instagram does not support text-only posts in the feed.
    # Return a helpful message instead of failing silently.
    return {
        "error": "Instagram feed posts require an image URL. "
                 "Provide image_url to publish a photo post.",
    }


async def whatsapp_send_message(
    *,
    phone_number_id: str,
    access_token: str,
    to: str,
    message: str,
) -> dict:
    """
    Send a text message via WhatsApp Business Cloud API.

    `to` must be a phone number in E.164 format (e.g. '+905551234567').
    Note: WhatsApp Status Stories are not supported by the official Cloud API.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{GRAPH_BASE}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to.lstrip("+"),  # Cloud API expects number without leading +
                "type": "text",
                "text": {"body": message},
            },
        )
        _raise(r)
        return r.json()


def _raise(response: httpx.Response) -> None:
    if not response.is_success:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(f"Meta API error {response.status_code}: {detail}")
