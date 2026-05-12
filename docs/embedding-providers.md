# Embedding providers — local models and BYO remote

Memtrace embeds every indexed symbol so semantic search ("how does
authentication work") can find code by meaning, not just keyword match.
You have three choices for **where** that embedding work happens:

1. **Local** (default) — Memtrace runs the model on your machine.
   Free, private, fast once warm. Eats RAM.
2. **Remote, hosted API** — Memtrace POSTs to OpenAI, Voyage, or any
   provider speaking the OpenAI-compatible embeddings spec. Costs
   credits but zero local compute.
3. **Remote, self-hosted** — Same wire format, but pointed at your own
   Ollama / Infinity / TEI / vLLM / LM Studio server. Free and private
   if you already run inference infra.

All three drive the same indexing and search pipelines. You switch
between them with one command — `memtrace embed set <preset>` or
`memtrace embed set --remote …`. Existing indexes get a clean
reset+reindex prompt on dim change; nothing silently corrupts.

This doc covers what each choice gets you, how to switch, and the
trade-offs that matter when you make the call.

## Quick decision guide

| If you… | Use |
|---|---|
| Have a Mac with ≥ 16 GB RAM and want it to "just work" | **Local `jina-code`** (default, code-tuned, 768-dim) |
| Are on a constrained machine (low RAM, Windows, locked-down corp laptop) | **Remote — Voyage or OpenAI** |
| Run Ollama / Infinity / TEI on a workstation already | **Remote — point at your own server** |
| Want faster local first-run and don't mind small-model retrieval quality | **Local `bge-small`** (384-dim, ~140 MB model) |
| Need top retrieval quality and have credits | **Remote `voyage-code-3`** (code-tuned, 1024-dim, Matryoshka) |
| Are in CI with no GPU | **Remote** — anything you have an API key for |

## The `memtrace embed` command

Four subcommands. `set` is the only one most users ever need.

```
memtrace embed list             # available local presets + currently active config
memtrace embed status           # detailed view: provider, model, dim, last health check
memtrace embed set <preset>     # switch to a local preset
memtrace embed set --remote …   # switch to a remote provider
memtrace embed test             # probe the configured provider; print latency + dim
```

`memtrace embed --help` prints the full surface.

### Local presets

```bash
memtrace embed list
```

```
Available local presets:
  jina-code   768d   (default; code-tuned)
  bge-small   384d   (smaller, faster, less RAM)
  bge-base    768d   (general-purpose)
  nomic       768d   (general-purpose)

Active: jina-code (local, 768d) — source: built-in default
```

Switch:

```bash
memtrace embed set bge-small
```

The CLI writes the choice to a persistent config file (see
[Persistent config](#persistent-config) below) so subsequent
`memtrace start` / `memtrace index` runs use the new model
automatically. If the new model has a different dim than your
existing `.memdb/`, the CLI prompts — see
[Dim-mismatch flow](#dim-mismatch-flow).

### Remote providers

```bash
memtrace embed set --remote openai-compat \
  --url <provider base URL> \
  --model <model name> \
  --api-key-env <ENV_VAR_NAME>
```

The adapter speaks the OpenAI-compatible `/embeddings` spec — same
request body shape, same response shape. Works as-is against:

| Provider | Base URL | Code-tuned model |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `text-embedding-3-small` (1536d), `text-embedding-3-large` (3072d) |
| Voyage AI | `https://api.voyageai.com/v1` | `voyage-code-3` (1024d default), `voyage-code-2` (1536d) |
| Ollama (local server) | `http://localhost:11434/v1` | `nomic-embed-text` (768d), `mxbai-embed-large` (1024d) |
| LM Studio | `http://localhost:1234/v1` | whichever embedding model you've loaded |
| Infinity | `http://localhost:7997/v1` | server-side configuration |
| TEI (Text Embeddings Inference) | `http://localhost:8080/v1` | server-side configuration |
| vLLM (with `--task embed`) | `http://localhost:8000/v1` | served model |

The `--api-key-env <ENV_VAR_NAME>` flag tells Memtrace which env
variable to read at request time. The key itself is **never written
to disk** — only the variable name is stored. So you set the key
once in your shell config and it stays out of every config file:

```bash
# In ~/.zshrc or ~/.bashrc:
export VOYAGE_API_KEY='vk-...'
export OPENAI_API_KEY='sk-...'
```

Then:

```bash
memtrace embed set --remote openai-compat \
  --url https://api.openai.com/v1 \
  --model text-embedding-3-small \
  --api-key-env OPENAI_API_KEY
```

For self-hosted servers that don't require auth (typical Ollama
setup), omit `--api-key-env`.

### Optional remote flags

| Flag | Default | What it does |
|---|---|---|
| `--timeout-ms <N>` | `30000` | Per-request HTTP timeout. Bump for slow networks or large batches. |
| `--max-batch <N>` | `64` | Maximum texts per request. Provider-side limits apply (OpenAI: 2048; Voyage: 128). |
| `--dim <N>` | (probe) | Force a specific dim via Matryoshka truncation. See [below](#matryoshka-dim-truncation). |

If you omit `--dim`, the CLI probes the endpoint with a one-token
test request and records whatever dim the provider returned.

### Verifying the config

```bash
memtrace embed status
```

```
provider     openai-compat
model        text-embedding-3-small
dim          1536
source       home (~/.memtrace/config.toml)
memdb_dim    1536                            (match)
last_health  2026-05-12T10:02:58Z OK 142ms dim=1536
url          https://api.openai.com/v1
request_timeout_ms   30000
max_batch    64
api_key_env  OPENAI_API_KEY (set)
```

`memdb_dim` is the dimensionality your existing `.memdb/` was built
with; if it doesn't match `dim`, search results will be wrong or
crash. The CLI's `set` flow always reconciles them — you only see a
mismatch here if something went sideways manually.

`last_health` is updated by `memtrace embed test`:

```bash
memtrace embed test
```

```
> OK  provider=openai-compat  dim=1536  latency=142ms
```

For local providers, `test` runs one embedding through the worker
and prints how long it took. For remote, it makes one HTTP call.

## Matryoshka dim truncation

Some modern embedding models (OpenAI's `text-embedding-3-*`, Voyage's
`voyage-code-3` / `voyage-4-*`) are **Matryoshka-trained** — you can
ask for a smaller dim and the model returns a truncation of the full
vector. The smaller vector is still semantically meaningful; you trade
a small recall hit for a big drop in HNSW memory and search latency.

To use it: pass `--dim N` when setting the remote provider.

```bash
# OpenAI text-embedding-3-small, truncated from 1536 → 512:
memtrace embed set --remote openai-compat \
  --url https://api.openai.com/v1 \
  --model text-embedding-3-small \
  --api-key-env OPENAI_API_KEY \
  --dim 512

# Voyage voyage-code-3, truncated from 1024 → 256:
memtrace embed set --remote openai-compat \
  --url https://api.voyageai.com/v1 \
  --model voyage-code-3 \
  --api-key-env VOYAGE_API_KEY \
  --dim 256
```

Common dim choices:

| Model | Supported dims (Matryoshka) | Sweet spot |
|---|---|---|
| `text-embedding-3-small` | 512 .. 1536 (continuous) | 768 or 1024 |
| `text-embedding-3-large` | 256 .. 3072 (continuous) | 1024 |
| `voyage-code-3` | 256, 512, 1024, 2048 | 1024 (default) |
| `voyage-4-large` | 256, 512, 1024, 2048 | 1024 |

If the provider doesn't support truncation, you'll get a clear
`DimMismatch` error on the first batch: the response arrived at the
provider's native dim instead of the dim you asked for. Drop the
`--dim` flag and re-run; the probe will record the native dim and
indexing will proceed.

## Persistent config

`memtrace embed set` writes the choice to a TOML file. Read precedence
from highest to lowest:

1. `<workspace>/.memtrace/embed.toml` — per-workspace, if you set with
   `--workspace`
2. `~/.memtrace/config.toml` — user default
3. `MEMTRACE_EMBED_MODEL` / `MEMTRACE_VECTOR_DIMS` env vars (transient
   escape hatch — useful in CI)
4. Built-in default: `jina-code` (local, 768d)

Example file written by `memtrace embed set --remote openai-compat …`:

```toml
version = 1

[embed]
provider = "openai-compat"
model = "text-embedding-3-small"
dim = 1536

[embed.remote]
url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
request_timeout_ms = 30000
max_batch = 64
```

You can edit this by hand if you prefer; Memtrace rejects unknown
keys with a clear error pointing you back at `memtrace embed set`.
Unknown `version` numbers (from a future release) get the same
treatment — your data is never silently misinterpreted.

### Workspace-scoped configs

Have one repo on local jina-code and another on remote Voyage?

```bash
cd ~/projects/repo-a
memtrace embed set jina-code --workspace      # writes ./.memtrace/embed.toml

cd ~/projects/repo-b
memtrace embed set --remote openai-compat \
  --url https://api.voyageai.com/v1 \
  --model voyage-code-3 \
  --api-key-env VOYAGE_API_KEY \
  --workspace                                  # writes ./.memtrace/embed.toml
```

Workspace configs require a `.memtrace-workspace` marker file at or
above the current directory (Memtrace creates one when you run
`memtrace start --workspace`; you can also `touch .memtrace-workspace`
yourself).

## Dim-mismatch flow

When you switch to a model with a different dim than the existing
`.memdb/`, the index is incompatible. The CLI surfaces this
interactively:

```bash
memtrace embed set bge-small
```

```
> Current MemDB: dim=768, 28490 nodes across 6 repos.
> Selected model produces dim=384. Cannot mix dims in one HNSW.
>   [r] Reset + reindex now
>   [c] Cancel  (config NOT written)
Choice [r/c]:
```

`r` wipes the `.memdb/` and re-indexes everything under the workspace.
`c` aborts — your old graph stays intact, the new config is NOT
written.

**Before the wipe, the CLI prints the exact path it's about to
remove**, in red, to stderr. If anything looks off (e.g. you expected
a scratch path and you see your home dir), `Ctrl-C` aborts cleanly.

For CI and non-interactive use:

```bash
memtrace embed set bge-small --yes-reset    # proceed without prompting
memtrace embed set bge-small --no-reset     # fail with exit-1 instead of prompting
```

`--yes-reset` and `--no-reset` are mutually exclusive; pass one or the
other.

## Switching back to local

Just `set` a local preset:

```bash
memtrace embed set jina-code
```

Same dim-mismatch flow if the new dim differs from your current one.
Your existing remote config (URL, API key env var, etc.) is forgotten
— a future `set --remote` writes it back.

## How searching works on each provider

| Phase | Local | Remote |
|---|---|---|
| **Indexing** (incremental and full) | ONNX model on your CPU / NPU | HTTP POST per batch of texts |
| **Query embedding** (every `find_code` call) | Same ONNX model | One HTTP POST per query |
| **Vector search** | In-process HNSW | In-process HNSW (provider never sees the search) |

Note the query path: when you ask `find_code "auth"`, Memtrace embeds
the query string through the same provider that indexed your code,
guaranteeing the query and document dims match. **Switch providers
and queries automatically follow** — no separate config.

If you watch your network: every `find_code` from your agent triggers
one small POST to the configured remote endpoint. For high-frequency
agents this adds up; consider how it interacts with provider rate
limits.

## Cost and performance comparison

Reference workload: indexing the MemFleet repo (~1,500 embeddable
symbols).

| Provider | Cold start | Warm | Cost per index | RAM (local) |
|---|---|---|---|---|
| Local `jina-code` (768d) | 5–6 min | ~3 min | $0 | ~500 MB resident |
| Local `bge-small` (384d) | ~1.5 min | ~50 s | $0 | ~250 MB |
| Voyage `voyage-code-3` (1024d) | ~80 s | ~80 s | ~$0.04 | minimal |
| OpenAI `text-embedding-3-small` (1536d) | varies (network) | varies | ~$0.02 | minimal |
| OpenAI `text-embedding-3-small` @ 512d (Matryoshka) | varies | varies | ~$0.02 | minimal |
| Ollama / self-hosted | depends on your hardware | depends | $0 | minimal (work is on the server) |

Cold-start vs warm matters more for local: the local path downloads
the ONNX model (~250 MB) and warms the runtime on first use. Remote
has no warm-up; every call is the same shape.

Per-query latency (single `find_code`):

| Provider | Typical |
|---|---|
| Local jina-code, warm | 10–50 ms |
| Voyage (US) from Europe | 300–500 ms |
| OpenAI (US) from Europe | 200–400 ms |
| Self-hosted Ollama on LAN | 5–30 ms |

## Privacy

- **Local** providers never leave your machine. Symbol bodies stay on
  disk in your `.memdb/`.
- **Remote** providers send your code-symbol bodies (function /
  class / method bodies, up to ~1500 characters each, plus query
  strings) over HTTPS to the configured endpoint. The provider's
  retention policy applies. Read it before pointing Memtrace at a
  third-party API on a confidential codebase.
- **Self-hosted remote** keeps everything on your hardware while
  giving you the HTTP-based architecture (handy in air-gapped
  workstations where you still want to swap models without touching
  the binary).

The API key itself is never written to Memtrace's config files — only
the env-variable name is. If you accidentally commit a config, no
secret leaks.

## Failure modes and their breakers

Memtrace's embedding pipeline has a circuit breaker that trips on
sustained failure and surfaces a clear remediation. Remote-provider
failures map to:

| Breaker reason | Triggered by | Remediation |
|---|---|---|
| `AuthFailed` | HTTP 401 / 403 | `memtrace embed set --remote … --api-key-env <VAR>`; check the env var resolves to a valid key |
| `RateLimited` | 3 consecutive HTTP 429s | Wait for the provider's `Retry-After`; adjust your agent call frequency or upgrade your plan |
| `NetworkUnavailable` | Connection refused / DNS failure / timeout / persistent 5xx | Verify the URL; for self-hosted, check the server is up |
| `DimMismatch` | Response vector has a different dim than configured | If you set `--dim N`, drop the flag and let the probe re-discover the native dim |

After a trip, run `memtrace embed reset-breaker` (or restart the
daemon) to clear it and resume.

## Troubleshooting

**"`memtrace embed set` is taking a long time" (>30 s)** — the probe
is waiting on the remote endpoint. Check your network and that the
URL is reachable (`curl -I <url>/embeddings`).

**"Indexing hangs at 0 batches dispatched"** — system memory pressure
gates local indexing. This shouldn't affect remote (remote uses zero
local RAM and the gate is provider-aware), but on a busy machine the
gate may still flag local runs. Workaround: `MEMTRACE_EMBED_PRESSURE=critical`
or `MEMTRACE_EMBED_PRESSURE=off` (the gate is documented in
[`environment-variables.md`](environment-variables.md)).

**"My agent's `find_code` returns nothing after switching providers"**
— this is a dim mismatch the CLI should have prevented. Run
`memtrace embed status` and check `memdb_dim` matches `dim`. If they
disagree, run `memtrace embed set <same provider> --yes-reset` to
realign.

**"`memtrace embed test` works but indexing fails immediately"** —
the probe and the indexing path go through the same adapter, so this
is rare. Usually means the provider returned a different dim for the
multi-text batch than the single-text probe (uncommon — most
providers are consistent). Drop `--dim` if you were forcing
truncation, and re-run.

## Reference: the wire shape

For provider operators or anyone curious. Memtrace sends:

```http
POST <base url>/embeddings
Authorization: Bearer <api key from env var>   (when api_key_env is set)
Content-Type: application/json

{
  "input": ["text 1", "text 2", "...up to max_batch"],
  "model": "<model name>",
  "dimensions": 512,         // only when --dim N was set; OpenAI's field
  "output_dimension": 512    // only when --dim N was set; Voyage's field
}
```

And expects:

```json
{
  "data": [
    {"embedding": [0.1, 0.2, ...], "index": 0},
    {"embedding": [0.3, 0.4, ...], "index": 1}
  ]
}
```

Any other keys in the response are tolerated and ignored. Both
`dimensions` (OpenAI) and `output_dimension` (Voyage) are sent
together when `--dim N` is configured — each provider honors the one
it knows and ignores the other.
