import json
import os
import httpx

# Cost tier: "low" (<$1/M input), "medium" ($1-5), "high" ($5-20), "premium" (>$20)
# Approximate input token prices per 1M tokens as of mid-2026.
# Update this table when providers change pricing.
_PRICING: dict[str, dict] = {
    # Anthropic
    "claude-haiku-4-5-20251001": {"tier": "low",     "input_per_m": 0.80,  "output_per_m": 4.00},
    "claude-sonnet-4-6":         {"tier": "medium",  "input_per_m": 3.00,  "output_per_m": 15.00},
    "claude-opus-4-7":           {"tier": "premium", "input_per_m": 15.00, "output_per_m": 75.00},
    # OpenAI
    "gpt-4o-mini":               {"tier": "low",     "input_per_m": 0.15,  "output_per_m": 0.60},
    "gpt-4o":                    {"tier": "medium",  "input_per_m": 2.50,  "output_per_m": 10.00},
    "o1-mini":                   {"tier": "medium",  "input_per_m": 3.00,  "output_per_m": 12.00},
    "o3-mini":                   {"tier": "medium",  "input_per_m": 1.10,  "output_per_m": 4.40},
    # Google
    "gemini-2.0-flash":          {"tier": "low",     "input_per_m": 0.10,  "output_per_m": 0.40},
    "gemini-2.5-pro":            {"tier": "medium",  "input_per_m": 1.25,  "output_per_m": 10.00},
    "gemini-2.5-flash":          {"tier": "low",     "input_per_m": 0.30,  "output_per_m": 2.50},
    # Mistral
    "mistral-small-latest":      {"tier": "low",     "input_per_m": 0.10,  "output_per_m": 0.30},
    "mistral-large-latest":      {"tier": "medium",  "input_per_m": 2.00,  "output_per_m": 6.00},
    "codestral-latest":          {"tier": "low",     "input_per_m": 0.20,  "output_per_m": 0.60},
    # Qwen
    "qwen-turbo":                {"tier": "low",     "input_per_m": 0.05,  "output_per_m": 0.20},
    "qwen-long":                 {"tier": "low",     "input_per_m": 0.14,  "output_per_m": 0.14},
    "qwen-plus":                 {"tier": "low",     "input_per_m": 0.40,  "output_per_m": 1.20},
    "qwen-max":                  {"tier": "medium",  "input_per_m": 1.60,  "output_per_m": 6.00},
}

_DEFAULT_PRICING = {"tier": "medium", "input_per_m": None, "output_per_m": None}

# ── Model capability cache ────────────────────────────────────────────────────

# Resolved at import time: backend/data/model_capabilities.json
_CAPABILITIES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "model_capabilities.json"
)

# Known image-generation model prefixes used as a classification fallback
_IMAGE_GEN_PREFIXES = (
    "wanx", "flux", "stable-diffusion", "dall-e", "qwen-image",
)


def _infer_model_type(model_id: str) -> str:
    """Classify a model as 'image' or 'chat' based on its ID."""
    m = model_id.lower()
    if any(m.startswith(p) for p in _IMAGE_GEN_PREFIXES):
        return "image"
    return "chat"


def load_model_capabilities() -> dict[str, str]:
    """Load {model_id: type} map from the capabilities cache file."""
    try:
        with open(_CAPABILITIES_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_model_capabilities(models: list[dict]) -> None:
    """
    Merge the given model list into the capabilities cache file.
    Each model dict must have 'id' and 'type' keys.
    Existing entries for other providers are preserved.
    """
    try:
        existing = load_model_capabilities()
    except Exception:
        existing = {}
    for m in models:
        mid = m.get("id")
        mtype = m.get("type")
        if mid and mtype:
            existing[mid] = mtype
    os.makedirs(os.path.dirname(_CAPABILITIES_PATH), exist_ok=True)
    with open(_CAPABILITIES_PATH, "w") as f:
        json.dump(existing, f, indent=2, sort_keys=True)


def _with_pricing(model_id: str, base: dict) -> dict:
    p = _PRICING.get(model_id, _DEFAULT_PRICING)
    model_type = _infer_model_type(model_id)
    return {**base, **p, "type": model_type}


LOCAL_PROVIDERS: set[str] = {"ollama", "lmstudio"}

PROVIDER_CONFIGS: dict[str, dict] = {
    "ollama": {
        "display_name": "Ollama (Lokal)",
        "url":          "__local__",
        "method":       "get",
        "headers":      lambda k: {"Authorization": f"Bearer {k}"},
        "body":         None,
        "models":       [],                 # fetched live from /v1/models
        "models_url":   "__local_dynamic__",
        "default_base_url": "http://localhost:11434/v1",
    },
    "lmstudio": {
        "display_name": "LM Studio (Lokal)",
        "url":          "__local__",
        "method":       "get",
        "headers":      lambda k: {"Authorization": f"Bearer {k}"},
        "body":         None,
        "models":       [],
        "models_url":   "__local_dynamic__",
        "default_base_url": "http://localhost:1234/v1",
    },
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
        # No public /models endpoint — use curated list above
        "models_url": None,
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
            {"id": "o3-mini",     "name": "o3 Mini"},
        ],
        "models_url": None,
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
        # Google exposes a live /models list — we prefer it but fall back to curated
        "models_url": "https://generativelanguage.googleapis.com/v1beta/models",
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
            {"id": "codestral-latest",     "name": "Codestral"},
        ],
        "models_url": "https://api.mistral.ai/v1/models",
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
        # models_url is dynamic (dashscope-intl vs dashscope); resolved via base_url at runtime
        "models_url": "__qwen_dynamic__",
    },
}

SUPPORTED_PROVIDERS = list(PROVIDER_CONFIGS.keys())


_QWEN_ENDPOINTS = [
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
]


def detect_qwen_base_url(plain_key: str) -> str | None:
    """Try both DashScope endpoints and return the base URL of whichever responds 200."""
    cfg = PROVIDER_CONFIGS["qwen"]
    for url in _QWEN_ENDPOINTS:
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json=cfg["body"], headers=cfg["headers"](plain_key))
            if resp.status_code in (200, 201):
                return url.rsplit("/chat/completions", 1)[0]
        except Exception:
            pass
    return None


def test_local_provider(base_url: str) -> bool:
    """Returns True if a local OpenAI-compatible server is reachable."""
    url = base_url.rstrip("/") + "/models"
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(url, headers={"Authorization": "Bearer local"})
        return resp.status_code in (200, 201)
    except Exception:
        return False


def test_provider_key(provider: str, plain_key: str, base_url: str | None = None) -> bool:
    """Returns True if the key/endpoint is valid for the given provider."""
    if provider == "qwen":
        return detect_qwen_base_url(plain_key) is not None

    if provider in LOCAL_PROVIDERS:
        resolved = base_url or PROVIDER_CONFIGS[provider].get("default_base_url", "")
        return test_local_provider(resolved)

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


def fetch_live_models(provider: str, plain_key: str, base_url: str | None = None) -> list[dict] | None:
    """
    Try to fetch the live model list from the provider API.
    Returns None if the provider has no models endpoint or the call fails.
    Each model dict has: id, name, tier, input_per_m, output_per_m.
    """
    cfg = PROVIDER_CONFIGS.get(provider, {})
    headers = cfg["headers"](plain_key)

    # Resolve models URL
    models_url = cfg.get("models_url")
    if models_url == "__qwen_dynamic__":
        resolved_base = base_url or detect_qwen_base_url(plain_key)
        if not resolved_base:
            return None
        models_url = f"{resolved_base}/models"
    elif models_url == "__local_dynamic__":
        resolved_base = base_url or cfg.get("default_base_url", "")
        if not resolved_base:
            return None
        models_url = resolved_base.rstrip("/") + "/models"
    elif not models_url:
        return None

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(models_url, headers=headers)
        if not resp.is_success:
            return None
        data = resp.json()
    except Exception:
        return None

    if provider == "google":
        raw = data.get("models", [])
        result = []
        for m in raw:
            mid = m.get("name", "").removeprefix("models/")
            mname = m.get("displayName", mid)
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            if not any(k in mid for k in ("gemini", "palm")):
                continue
            result.append(_with_pricing(mid, {"id": mid, "name": mname}))
        return result or None

    if provider == "mistral":
        raw = data.get("data", [])
        result = []
        for m in raw:
            mid = m.get("id", "")
            mname = mid.replace("-", " ").title()
            result.append(_with_pricing(mid, {"id": mid, "name": mname}))
        return result or None

    if provider == "qwen":
        raw = data.get("data", [])
        result = []
        for m in raw:
            mid = m.get("id", "")
            if not mid:
                continue
            result.append(_with_pricing(mid, {"id": mid, "name": mid}))
        return result or None

    if provider in LOCAL_PROVIDERS:
        raw = data.get("data", [])
        result = []
        for m in raw:
            mid = m.get("id", m.get("name", ""))
            if not mid:
                continue
            mname = mid.split("/")[-1] if "/" in mid else mid
            result.append({"id": mid, "name": mname, "tier": "low", "input_per_m": 0.0, "output_per_m": 0.0, "type": "chat"})
        return result or None

    return None


def get_provider_models(provider: str, plain_key: str | None = None, base_url: str | None = None) -> list[dict]:
    """
    Return models for a provider with pricing metadata.
    If plain_key is provided and the provider has a live endpoint, fetches dynamically.
    Falls back to the curated list when live fetch is unavailable or fails.
    base_url is used for providers like qwen where the endpoint varies per key.
    """
    cfg = PROVIDER_CONFIGS.get(provider, {})
    curated = [
        _with_pricing(m["id"], {"provider": provider, **m})
        for m in cfg.get("models", [])
    ]

    if plain_key:
        live = fetch_live_models(provider, plain_key, base_url=base_url)
        if live:
            return [{"provider": provider, **m} for m in live]

    return curated
