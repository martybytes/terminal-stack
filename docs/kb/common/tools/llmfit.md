# llmfit (right-size LLM models to your hardware)

Detects your system's RAM, CPU, and GPU (NVIDIA, AMD, Apple Silicon), scores
every model in its database for fit/speed/quality, and can recommend, compare,
plan hardware, download GGUF weights, and launch inference — one binary, no
external services required for the read-only commands.

## Daily commands
| Command | What |
|---|---|
| `llmfit system` | detected RAM/CPU/GPU for this machine |
| `llmfit fit` | ranked table of models that fit, classic CLI output |
| `llmfit fit -p` | only models that perfectly match recommended specs |
| `llmfit recommend` | top-N ranked recommendations (JSON by default) |
| `llmfit recommend --use-case coding --min-fit good` | filtered recommendations |
| `llmfit list` | every model in the embedded database, no hardware scoring |
| `llmfit search <query>` | look up models by name/provider/size |
| `llmfit info <model>` | full spec + fit analysis for one model |
| `llmfit diff <a> <b>` | side-by-side compare two models |
| `llmfit diff` | auto-compare the top 2 filtered models |
| `llmfit plan <model> --context 8192` | VRAM/RAM + throughput estimate at a given context/quant |
| `llmfit download <model>` | fetch a GGUF from HuggingFace into the local model cache |
| `llmfit run <model>` | interactive chat with a downloaded GGUF via llama-cli |
| `llmfit run <model> --server --port 8080` | OpenAI-compatible API server |

Any subcommand takes `-h`/`--help` for its full flag list; `llmfit help <cmd>`
works too.

## Exporting results to a file

There's no dedicated `--output <file>` flag — `--json` and `--csv` just switch
the stdout format, so redirect it:

```sh
llmfit fit --json > fit.json
llmfit fit --csv  > fit.csv
llmfit recommend -n 10 --use-case coding --json > recommend.json   # --json is already the default here
llmfit info "llama-3.1-8b" --json > llama-3.1-8b.json
llmfit plan "qwen-72b" --context 4096 --json > plan.json
```

Works on `system`, `fit`, `list`, `info`, `diff`, `plan`, `recommend`, `update`,
and `bench`. **`search`, `download`, `hf-search`, and `run` accept the flag but
don't actually emit structured output** — the built-in help for each says so
explicitly ("No --json support for this command"); for those, either parse
the plain stdout or go through `llmfit list --json` / `llmfit info --json`
instead. Exit code is always `0` on success / `1` on error, so redirection is
safe to script against (`llmfit fit --json > f.json || echo "failed"`).

For a long-running/programmatic source instead of one-shot files, `llmfit
serve --port 8787` exposes the same data over a local REST API (add `--mcp`
to run it as an MCP server on stdio instead of HTTP).

## Hardware overrides

`--memory`, `--ram`, `--cpu-cores`, `--max-context` (global flags, valid on
every subcommand) override autodetection — useful when scoring fit for a
*different* machine than the one you're running on, e.g.
`llmfit fit --ram 64G --memory 24G --json > target-box.json`.
