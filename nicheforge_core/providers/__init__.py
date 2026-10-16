"""Key Ladder: unified chat-completion interface with automatic failover
across free LLM providers.

Failover order: Gemini -> Groq -> NVIDIA NIM -> OpenRouter (:free) -> Pollinations (no key) -> Z.ai GLM Flash.

Public API:
    from providers import KeyLadder, load_config, log_usage, get_usage
"""

from .crypto import decrypt_config, encrypt_config
from .ladder import KeyLadder, load_config
from .usage import get_usage, log_usage

__all__ = ["KeyLadder", "load_config", "log_usage", "get_usage", "encrypt_config", "decrypt_config"]
