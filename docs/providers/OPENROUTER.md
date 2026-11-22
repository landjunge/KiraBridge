# OpenRouter API in KiraBridge

Checked against OpenRouter's public model catalog on **22 November 2026**. This
adapter sends bounded Chat Completions requests for each KiraBridge task. It
does not run local commands or resume provider sessions. Explicitly granted
tool calls use the existing task-scoped KiraBridge MCP proxy.

## Provider and credential source

The endpoint is fixed to `https://openrouter.ai/api/v1/chat/completions`; a
profile cannot redirect the API key to another host.

Use the fixed `OPENROUTER_API_KEY` environment variable for servers and
cross-platform deployments. On macOS desktop installs, an explicit
`macos_keychain` source can read the fixed `KiraBridge.OpenRouter` / `openrouter`
generic-password item into memory. `kirabridge openrouter credential-import`
uses the system `security` tool's hidden TTY prompt; the key is not placed in an
argument, file, or log. `kirabridge openrouter credential-status` reports only
whether the item exists. This does not import or read the separate OpenCode
credential: that CLI has no targeted export command, and its SQLite key rows
have no safe provider mapping. The adapter never saves the key, returns it in
task evidence, or includes it in an error.

```toml
[agents.openrouter]
kind = "openrouter_api"
openrouter_credential_source = "environment"
model = "particle-ai/particle-1:free"
openrouter_fallback_models = ["baidu/ernie-5.5-flash-preview:free"]
openrouter_max_prompt_bytes = 262144
openrouter_max_output_tokens = 1024
openrouter_allow_paid = false
# Optional: only these no-shell MCP bridge tools are eligible for exposure.
bridge_tools = true
openrouter_mcp_tools = ["task_request", "task_get"]
openrouter_mcp_operations = ["file.read", "file.list", "file.write"]
openrouter_mcp_read_roots = []
openrouter_max_tool_calls = 8
openrouter_max_turns = 4
openrouter_max_tool_result_bytes = 32768
```

Provide `OPENROUTER_API_KEY` to the KiraBridge service. The config stores only
the fixed variable name. On a macOS desktop, use
`openrouter_credential_source = "macos_keychain"` after importing the item with
the local CLI. Server deployments must use the environment source. Add the agent identity to the existing principal's
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
DeepSeek requests also send OpenRouter's hard `provider.max_price` filter at
those per-million-token rates. The task cost cap separately reserves the
maximum input/output spend across every allowed model turn.

## Tool and data scope

OpenRouter's catalog reports tool-call support for the pinned models. KiraBridge
uses the existing task-scoped stdio MCP proxy and `AgentTaskPolicy`, which bind
the task, owner, arguments and CWD, filter the tool catalog, recheck permissions
per call and consume the task call budget before dispatch. OpenRouter's separate
operator allowlist accepts only `task_request`, `task_get`, `task_events`,
`read_query`, and bridge status/catalog tools. Child operations are limited to
`file.read`, `file.list`, `file.write`, and `file.mkdir`, scoped by current
principal roots and task CWD. Shell, terminal, and arbitrary operation dispatch
are not exposed. File writes additionally require explicit operator and
principal local-tool grants plus task-supplied operation scope. Tool turns,
calls, results, request bytes and total paid cost are bounded; an uncertain MCP
outcome is never replayed automatically.

OpenRouter reports that these free endpoints are not available through EU
in-region routing at the checked date. Send only data authorized for that
provider route.

## Official references

- [OpenRouter model catalog API](https://openrouter.ai/api/v1/models)
- [Particle-1 free model](https://openrouter.ai/particle-ai/particle-1:free)
- [DeepSeek V4.1 Flash](https://openrouter.ai/deepseek/deepseek-v4.1-flash)
- [OpenRouter free models and rate limits](https://openrouter.ai/collections/free-models)
- [OpenRouter model fallback routing](https://openrouter.ai/blog/insights/model-routing/)
- [OpenRouter `provider.max_price`](https://openrouter.ai/docs/guides/routing/provider-selection#max-price)
- [OpenCode provider credential export](https://opencode.ai/docs/cli/providers/)
