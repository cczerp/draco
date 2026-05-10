# 🐉 Draco

A local AI agent for your terminal — runs on your machine, talks to your files, executes commands. Like having Claude Code but powered by local Ollama models (or Nebius cloud if you prefer).

## Install

One-liner:
```bash
curl -fsSL https://raw.githubusercontent.com/cczerp/draco/main/install.sh | bash
```

Or clone and run:
```bash
git clone https://github.com/cczerp/draco
bash draco/install.sh
```

No sudo? Use `--user` to install to `~/.local/bin`:
```bash
bash draco/install.sh --user
```

**Requirements:** Python 3.8+, internet connection for first-time model download.  
No Docker needed. No cloud account needed (unless you want one).

---

## First run

Just type `draco`. The setup wizard handles everything:

- **No Ollama?** → offers to show you the install command
- **No models?** → asks permission to download a starter model (~1.5 GB)
- **No Ollama at all?** → offers to connect a Nebius cloud API key instead

---

## Usage

```bash
draco                                  # interactive session
draco "what's eating my disk space?"   # single prompt
draco --dangerously-skip-permissions   # auto-approve all tool calls
draco --model llama3.2:3b              # pick a specific model
echo "summarize this" | draco          # pipe input
```

## Commands (inside draco)

| Command | What it does |
|---|---|
| `/models` | list models available on your machine |
| `/model <name>` | switch to a different model |
| `/pull <name>` | download a new Ollama model |
| `/backend nebius` | switch to Nebius cloud inference |
| `/backend ollama` | switch back to local |
| `/credentials` | add or update your Nebius API key |
| `/docker` | step-by-step Docker install/setup |
| `/clear` | clear conversation history |
| `/help` | show all commands |
| `/exit` | quit |

## Tools Draco can use

- **run_command** — runs any shell command on your machine
- **read_file** — reads any file
- **write_file** — writes/creates files
- **list_directory** — lists directory contents

Each tool call asks for your permission before running (unless you pass `--dangerously-skip-permissions`).

## Nebius cloud (optional)

If you want faster/larger models without a GPU, Draco supports [Nebius AI Studio](https://studio.nebius.ai/):

1. Get an API key at studio.nebius.ai → API Keys
2. Run `draco` and type `/credentials`
3. Paste your key — it's saved to `~/.config/draco/config.json`

Switch between local and cloud anytime with `/backend ollama` or `/backend nebius`.

## Models

Good starting models (install with `/pull <name>`):

| Model | Size | Good for |
|---|---|---|
| `qwen3.5:2b` | ~1.5 GB | fast, low RAM (default) |
| `llama3.2:3b` | ~2 GB | general use |
| `qwen2.5-coder:7b` | ~4.7 GB | code tasks |
| `llama3.1:8b` | ~5 GB | best quality local |
