"""Pinned zero-price OpenRouter model routes, checked against the public catalog."""

OPENROUTER_DEFAULT_MODEL = "particle-ai/particle-1:free"
OPENROUTER_DEFAULT_FALLBACKS = ("baidu/ernie-5.5-flash-preview:free",)

# The :free suffix is required. These IDs were present in OpenRouter's public
# model catalog on 2026-11-22 and both advertised $0 prompt/completion pricing.
# Tool support is catalog metadata only; this adapter does not dispatch tools.
OPENROUTER_FREE_MODELS = frozenset(
    {
        OPENROUTER_DEFAULT_MODEL,
        *OPENROUTER_DEFAULT_FALLBACKS,
    }
)

# One explicitly reviewed paid option. It is never a free-route fallback.
OPENROUTER_PAID_MODELS = frozenset({"deepseek/deepseek-v4.1-flash"})
OPENROUTER_TOOL_MODELS = frozenset(
    {
        OPENROUTER_DEFAULT_MODEL,
        *OPENROUTER_DEFAULT_FALLBACKS,
        *OPENROUTER_PAID_MODELS,
    }
)

# OpenRouter provider.max_price is expressed in USD per 1M input/output tokens.
OPENROUTER_DEEPSEEK_MAX_PRICE = {"prompt": 0.0498, "completion": 0.1992}

OPENROUTER_MODELS_API = "https://openrouter.ai/api/v1/models"
OPENROUTER_CHAT_API = "https://openrouter.ai/api/v1/chat/completions"
