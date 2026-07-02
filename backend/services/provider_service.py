import httpx

PROVIDER_CONFIGS: dict[str, dict] = {
    "anthropic": {
        "display_name": "Anthropic (Claude)",
        "url":     "https://api.anthropic.com/v1/messages",
        "method":  "post",
        "headers": lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        "body":    {"model": "claude-haiku-4-5-20251001", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
        "models": [
            {"id": "claude-opus-4-7",          "name": "Claude Opus 4.7"},
            {"id": "claude-sonnet-4-6",         "name": "Claude Sonnet 4.6"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
        ],
    },
    "openai": {
        "display_name": "OpenAI (GPT)",
        "url":     "https://api.openai.com/v1/chat/completions",
        "method":  "post",
        "headers": lambda k: {"Authorization": f"Bearer {k}", "content-type": "application/json"},
        "body":    {"model": "gpt-4o-mini", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
        "models": [
            {"id": "gpt-4o",      "name": "GPT-4o"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
            {"id": "o1-mini",     "name": "o1 Mini"},
        ],
    },
    "google": {
        "display_name": "Google (Gemini)",
        "url":     "https://generativelanguage.googleapis.com/v1beta/models",
        "method":  "get",
        "headers": lambda k: {"x-goog-api-key": k},
        "body":    None,
        "models": [
            {"id": "gemini-2.5-pro",   "name": "Gemini 2.5 Pro"},
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
        ],
    },
    "mistral": {
        "display_name": "Mistral AI",
        "url":     "https://api.mistral.ai/v1/models",
        "method":  "get",
        "headers": lambda k: {"Authorization": f"Bearer {k}"},
        "body":    None,
        "models": [
            {"id": "mistral-large-latest", "name": "Mistral Large"},
            {"id": "mistral-small-latest", "name": "Mistral Small"},
        ],
    },
    "qwen": {
        "display_name": "Alibaba Qwen",
        "url":     "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "method":  "post",
        "headers": lambda k: {"Authorization": f"Bearer {k}", "content-type": "application/json"},
        "body":    {"model": "qwen-turbo", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
        "models": [
            {"id": "qwen-max",   "name": "Qwen Max"},
            {"id": "qwen-plus",  "name": "Qwen Plus"},
            {"id": "qwen-turbo", "name": "Qwen Turbo"},
            {"id": "qwen-long",  "name": "Qwen Long"},
        ],
    },
}

SUPPORTED_PROVIDERS = list(PROVIDER_CONFIGS.keys())


def test_provider_key(provider: str, plain_key: str) -> bool:
    """Returns True if the key is valid for the given provider."""
    cfg = PROVIDER_CONFIGS.get(provider)
    if not cfg:
        return False
    try:
        with httpx.Client(timeout=10) as client:
            kwargs: dict = {"headers": cfg["headers"](plain_key)}
            if cfg["body"]:
                kwargs["json"] = cfg["body"]
            fn = client.post if cfg["method"] == "post" else client.get
            resp = fn(cfg["url"], **kwargs)
        return resp.status_code in (200, 201)
    except Exception:
        return False


def get_provider_models(provider: str) -> list[dict]:
    return [{"provider": provider, **m} for m in PROVIDER_CONFIGS[provider]["models"]]
