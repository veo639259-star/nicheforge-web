"""KeyLadder: unified chat-completion interface with automatic failover.

Failover order is fixed: Gemini -> Groq -> NVIDIA NIM -> OpenRouter (:free)
-> Pollinations (no key needed) -> Z.ai GLM Flash.

Within each provider every key is tried with every model before the ladder
moves to the next provider. Key values are never logged (masked as ****XXXX).
"""

import requests

from .crypto import decrypt_config
from .usage import log_usage

# Failover order. Only structure lives here -- no real keys.
_ORDER = ["gemini", "groq", "nvidia", "openrouter", "pollinations", "zai"]

_DEFAULTS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-2.5-flash"],
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile"],
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "models": ["meta/llama-3.3-70b-instruct"],
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["meta-llama/llama-3.3-70b-instruct:free"],
    },
    "pollinations": {
        "base_url": "https://text.pollinations.ai/openai",
        "models": ["openai"],
    },
    "zai": {
        "base_url": "https://api.z.ai/api/paas/v4",
        "models": ["glm-4.5-flash"],
    },
}

# Extra headers some providers expect for an OpenAI-compatible call.
_EXTRA_HEADERS = {
    "openrouter": {"HTTP-Referer": "https://nicheforge.local", "X-Title": "NicheForge"},
}


def mask_key(key: str) -> str:
    """Mask a key for logs: 'sk-abc...z9' -> '****z9'."""
    key = str(key)
    return "****" + key[-4:] if len(key) >= 4 else "****"


def load_config(path: str, password: str) -> dict:
    """Load and decrypt an encrypted config file produced by setup_keys.py."""
    with open(path, "rb") as fh:
        blob = fh.read()
    return decrypt_config(blob, password)


class KeyLadder:
    """config shape::

        {"providers": [
            {"name": "gemini",
             "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
             "models": ["gemini-2.5-flash"],
             "keys": ["KEY1"]},
            ...
        ]}

    Missing provider entries fall back to the defaults above (except keys,
    which default to [] -- a provider with no keys is skipped, except
    pollinations which needs no key).
    """

    def __init__(self, config: dict, db_path: str):
        self.db_path = db_path
        by_name = {p.get("name"): p for p in (config or {}).get("providers", [])}
        self.providers = []
        for name in _ORDER:
            entry = by_name.get(name, {}) or {}
            default = _DEFAULTS[name]
            self.providers.append({
                "name": name,
                "base_url": entry.get("base_url") or default["base_url"],
                "models": entry.get("models") or list(default["models"]),
                "keys": entry.get("keys") or [],
            })

    def _call_once(self, provider: dict, key: str, model: str, messages: list,
                   max_tokens: int, timeout: int) -> dict:
        url = provider["base_url"].rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        headers.update(_EXTRA_HEADERS.get(provider["name"], {}))
        # Pollinations needs no key; send a dummy bearer so the request shape
        # stays OpenAI-compatible everywhere.
        headers["Authorization"] = "Bearer " + (key or "dummy")
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("no choices in response")
        if not text or not str(text).strip():
            raise RuntimeError("empty reply")
        usage = data.get("usage") or {}
        return {
            "provider": provider["name"],
            "model": model,
            "text": str(text).strip(),
            "tokens_in": int(usage.get("prompt_tokens") or 0),
            "tokens_out": int(usage.get("completion_tokens") or 0),
        }

    def chat(self, messages: list, system: str = None, timeout: int = 60,
             max_tokens: int = 1024) -> dict:
        """Try each provider/key/model in failover order.

        Returns {"provider","model","text","tokens_in","tokens_out"}.
        Raises RuntimeError("all providers failed: ...") listing per-provider
        errors when nothing works.
        """
        msgs = [{"role": "system", "content": system}] if system else []
        msgs.extend(messages or [])

        errors = []
        for provider in self.providers:
            name = provider["name"]
            keys = provider["keys"] or ([""] if name == "pollinations" else [])
            if not keys:
                errors.append(f"{name}: no keys configured")
                continue
            last_err = None
            for key in keys:
                for model in provider["models"]:
                    try:
                        result = self._call_once(
                            provider, key, model, msgs, max_tokens, timeout)
                    except Exception as exc:  # noqa: BLE001 - ladder must be fault-tolerant
                        log_usage(self.db_path, name, model, ok=0)
                        last_err = f"{name} key={mask_key(key)} model={model}: {exc}"
                        continue
                    log_usage(self.db_path, name, model,
                              tokens_in=result["tokens_in"],
                              tokens_out=result["tokens_out"], ok=1)
                    return result
            errors.append(f"{name}: {last_err}" if last_err else f"{name}: all keys/models failed")
        raise RuntimeError("all providers failed: " + " | ".join(errors))
