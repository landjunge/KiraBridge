# OpenRouter API in KiraBridge

Checked against OpenRouter's public model catalog on **22 November 2026**. This
adapter sends one bounded, text-only Chat Completions request per KiraBridge
task. It does not run local commands, access files, resume provider sessions, or
execute model tool calls.

## Provider and credential source

The endpoint is fixed to `https://openrouter.ai/api/v1/chat/completions`; a
profile cannot redirect the API key to another host.

Use the explicitly named `OPENROUTER_API_KEY` environment variable. The
adapter does not read OpenCode's credential store: the installed OpenCode CLI
does not provide a targeted `auth export` command. Its existing OpenRouter
credential therefore cannot be consumed through a supported safe resolver.
Do not copy it into a plaintext file. The adapter reads the environment value
only in memory, sends it in the HTTPS Authorization header, and never saves,
returns it in task evidence, or includes it in an error. Missing credentials
stop the task.

```toml
[agents.openrouter]
kind = "openrouter_api"
openrouter_credential_source = "environment"
model = "particle-ai/particle-1:free"
openrouter_fallback_models = ["baidu/ernie-5.5-flash-preview:free"]
openrouter_max_prompt_bytes = 262144
openrouter_max_output_tokens = 1024
openrouter_allow_paid = false
```

Provide `OPENROUTER_API_KEY` to the KiraBridge service. The config stores only
the variable name. Add the agent identity to the existing principal's
agent allowlist and use normal `task_request` / `task_get` permissions.

## Free and paid routing

The default fixed coding route is `particle-ai/particle-1:free`, with the
explicit free fallback `baidu/ernie-5.5-flash-preview:free`. Both IDs were in
OpenRouter's public catalog at the checked date with zero prompt and completion
prices. The adapter sends them through the `models` fallback list in one
provider request. It does not use `openrouter/free`, whose model selection is
dynamic.

Non-free models are rejected by default. Enabling one requires an explicit
model from the reviewed paid set (currently only
`deepseek/deepseek-v4.1-flash`), `openrouter_allow_paid = true`, and all of:

```toml
openrouter_paid_max_prompt_bytes = 32768
openrouter_paid_max_output_tokens = 512
openrouter_paid_max_cost_usd = 0.01
```

Before a paid request, KiraBridge reads the public OpenRouter model catalog,
uses the highest listed prompt/completion rate (including pricing overrides),
and computes a conservative bound from UTF-8 prompt bytes plus framing overhead
and the configured maximum output tokens. Missing price data or a cost above
the cap blocks the request. Paid model fallback is not enabled. Each task makes
at most one Chat Completions request and the adapter never retries an uncertain
outcome.

The provider itself limits free variants; the current OpenRouter documentation
lists 20 requests/minute and 50/day, with a higher daily limit only after buying
credits. A 429 remains a bounded task failure; KiraBridge does not spend extra
requests to retry it.

DeepSeek V4.1 Flash is currently listed at $0.0498/M input and $0.1992/M output
tokens. It is never selected by the free route and never used as an automatic
fallback. OpenRouter describes the free `particle-ai/particle-1:free` model as
post-trained on DeepSeek V4.1 Flash; it remains the default route.

## Tool and data scope

OpenRouter's catalog currently reports tool-call support for the two pinned
models. This adapter deliberately sends no `tools` field and rejects MCP grants
or local-tool requests until a separately scoped tool executor is reviewed.
The model can therefore return coding advice/text, but cannot edit the project
through KiraBridge in this adapter.

OpenRouter reports that these free endpoints are not available through EU
in-region routing at the checked date. Send only data authorized for that
provider route.

## Official references

- [OpenRouter model catalog API](https://openrouter.ai/api/v1/models)
- [Particle-1 free model](https://openrouter.ai/particle-ai/particle-1:free)
- [DeepSeek V4.1 Flash](https://openrouter.ai/deepseek/deepseek-v4.1-flash)
- [OpenRouter free models and rate limits](https://openrouter.ai/collections/free-models)
- [OpenRouter model fallback routing](https://openrouter.ai/blog/insights/model-routing/)
- [OpenCode provider credential export](https://opencode.ai/docs/cli/providers/)
