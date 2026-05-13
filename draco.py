#!/usr/bin/env python3
"""
Draco — local AI agent with full system access.
Usage: draco [--dangerously-skip-permissions] [--model MODEL] [prompt]
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import platform
import shutil

try:
    import readline  # noqa: F401  — arrow-key history; Linux/Mac only
except ImportError:
    pass  # not available on Windows — that's fine

try:
    import requests
except ImportError:
    print('\n  requests not installed. Fixing that now...\n')
    import subprocess as _sp
    _sp.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', 'requests'])
    import requests

# ── ANSI colours ──────────────────────────────────────────────────────────────
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleMode(
            ctypes.windll.kernel32.GetStdHandle(-11), 7)
        P='\033[95m'; C='\033[96m'; G='\033[92m'; Y='\033[93m'; R='\033[91m'
        B='\033[1m';  D='\033[2m';  X='\033[0m'
    except Exception:
        P=C=G=Y=R=B=D=X=''
else:
    P='\033[95m'; C='\033[96m'; G='\033[92m'; Y='\033[93m'; R='\033[91m'
    B='\033[1m';  D='\033[2m';  X='\033[0m'

# ── Constants ─────────────────────────────────────────────────────────────────
OLLAMA_BASE    = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
NEBIUS_BASE    = 'https://api.studio.nebius.ai/v1'
DEFAULT_MODEL  = os.environ.get('DRACO_MODEL', 'qwen2.5-coder:7b')
FALLBACK_MODEL = 'qwen2.5-coder:7b'

MODEL_ALIASES = {
    'coder': 'qwen2.5-coder:7b',
    'dolph': 'tinydolphin:latest',
}
CONFIG_FILE = Path.home() / '.config' / 'draco' / 'config.json'

# ── Runtime state ─────────────────────────────────────────────────────────────
_chat_url = OLLAMA_BASE.rstrip('/') + '/v1/chat/completions'
_headers  = {}
_backend  = 'ollama'
_models   = []


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}

def save_config(cfg: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# ── Ollama helpers ────────────────────────────────────────────────────────────

def get_ollama_models() -> list | None:
    try:
        r = requests.get(f'{OLLAMA_BASE}/api/tags', timeout=4)
        if r.ok:
            return [m['name'] for m in r.json().get('models', [])]
    except Exception:
        pass
    return None

def pull_model(model_name: str) -> bool:
    print(f'\n{C}  Downloading {B}{model_name}{X}{C} …{X}')
    print(f'{D}  (this may take several minutes — you can Ctrl+C to cancel){X}\n')
    try:
        resp = requests.post(
            f'{OLLAMA_BASE}/api/pull',
            json={'name': model_name},
            stream=True, timeout=1800
        )
        last_status = ''
        for raw in resp.iter_lines():
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            status = data.get('status', '')
            if 'total' in data and data['total']:
                done  = data.get('completed', 0)
                total = data['total']
                pct   = int(done / total * 100)
                bar   = ('█' * (pct // 5)).ljust(20)
                print(f'\r  {C}{bar}{X} {pct:3d}%  {D}{status}{X}   ', end='', flush=True)
            elif status != last_status:
                print(f'\r  {D}{status}{X}' + ' ' * 40, end='', flush=True)
                last_status = status
        print(f'\n\n{G}  ✓ {model_name} ready{X}\n')
        return True
    except KeyboardInterrupt:
        print(f'\n{Y}  Download cancelled.{X}\n')
        return False
    except Exception as e:
        print(f'\n{R}  Pull failed: {e}{X}\n')
        return False


# ── Nebius helpers ────────────────────────────────────────────────────────────

def get_nebius_models(api_key: str) -> list:
    try:
        r = requests.get(
            f'{NEBIUS_BASE}/models',
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=8
        )
        if r.ok:
            return sorted(m['id'] for m in r.json().get('data', []))
    except Exception:
        pass
    return []

def prompt_nebius_credentials() -> str | None:
    print(f'\n{P}{B}  Nebius API Setup{X}')
    print(f'{D}  Get your key at: https://studio.nebius.ai/ → API Keys{X}\n')
    try:
        key = input(f'  {Y}Paste your Nebius API key (or Enter to skip): {X}').strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not key:
        return None
    cfg = load_config()
    cfg['nebius_api_key'] = key
    save_config(cfg)
    print(f'{G}  ✓ Saved to {CONFIG_FILE}{X}\n')
    return key


# ── Backend activation ────────────────────────────────────────────────────────

def activate_ollama(models: list):
    global _chat_url, _headers, _backend, _models
    _chat_url = OLLAMA_BASE.rstrip('/') + '/v1/chat/completions'
    _headers  = {}
    _backend  = 'ollama'
    _models   = models

def activate_nebius(api_key: str, models: list):
    global _chat_url, _headers, _backend, _models
    _chat_url = NEBIUS_BASE.rstrip('/') + '/chat/completions'
    _headers  = {'Authorization': f'Bearer {api_key}'}
    _backend  = 'nebius'
    _models   = models

def pick_model(requested: str, available: list) -> str:
    resolved = MODEL_ALIASES.get(requested, requested) if requested else requested
    if resolved and resolved in available:
        return resolved
    base = (resolved or FALLBACK_MODEL).split(':')[0]
    alts = [m for m in available if m.split('/')[-1].lower().startswith(base.lower())]
    chosen = alts[0] if alts else available[0]
    if resolved and chosen != resolved:
        print(f'{Y}  Model "{resolved}" not found — using {chosen} instead.{X}')
        print(f'{D}  To get it: /pull {resolved}{X}\n')
    return chosen


# ── Docker helpers ────────────────────────────────────────────────────────────

def check_docker() -> str:
    if not shutil.which('docker'):
        return 'not_installed'
    try:
        r = subprocess.run(['docker', 'ps'], capture_output=True, timeout=5)
        if r.returncode == 0:
            return 'ok'
        stderr = r.stderr.decode('utf-8', errors='replace').lower()
        if 'permission denied' in stderr:
            return 'no_permission'
        return 'not_running'
    except Exception:
        return 'not_running'

def run_docker_setup():
    status = check_docker()

    if status == 'ok':
        print(f'{G}  ✓ Docker is already installed and running.{X}\n')
        return

    print(f'\n{P}{B}  Docker Setup{X}\n')

    if status == 'not_installed':
        print(f'  Docker is not installed.\n')
        print(f'  {B}Step 1{X} — Install Docker via the official script:')
        print(f'  {D}  curl -fsSL https://get.docker.com | sh{X}\n')
        try:
            ans = input(f'  {Y}Run the install script now? [Y/n]: {X}').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if ans in ('', 'y', 'yes'):
            print(f'\n{C}  Running Docker install script…{X}\n')
            r = subprocess.run('curl -fsSL https://get.docker.com | sh', shell=True)
            if r.returncode != 0:
                print(f'\n{R}  Install failed.{X} Try manually:')
                print(f'  curl -fsSL https://get.docker.com | sh\n')
                return
            print(f'\n{G}  ✓ Docker installed.{X}\n')
            status = 'no_permission'
        else:
            print(f'{D}  Skipping.{X}\n')
            return

    if status == 'no_permission':
        user = os.environ.get('USER', 'paul')
        print(f'  {B}Step 2{X} — Add {user} to the docker group:')
        print(f'  {D}  sudo usermod -aG docker {user}{X}\n')
        try:
            ans = input(f'  {Y}Run this now? [Y/n]: {X}').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if ans in ('', 'y', 'yes'):
            r = subprocess.run(['sudo', 'usermod', '-aG', 'docker', user])
            if r.returncode == 0:
                print(f'{G}  ✓ Added to docker group.{X}')
                print(f'{Y}  ⚠  Log out and back in to apply,  or run: newgrp docker{X}\n')
            else:
                print(f'{R}  Failed.{X} Run manually: sudo usermod -aG docker {user}\n')
        return

    if status == 'not_running':
        print(f'  Docker is installed but the daemon is not running.\n')
        print(f'  {B}Step 3{X} — Start Docker and enable it on boot:')
        print(f'  {D}  sudo systemctl enable --now docker{X}\n')
        try:
            ans = input(f'  {Y}Start Docker now? [Y/n]: {X}').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if ans in ('', 'y', 'yes'):
            r = subprocess.run(['sudo', 'systemctl', 'enable', '--now', 'docker'])
            if r.returncode == 0:
                print(f'{G}  ✓ Docker started and enabled on boot.{X}\n')
            else:
                print(f'{R}  Failed.{X} Try: sudo systemctl start docker\n')


# ── Startup ───────────────────────────────────────────────────────────────────

def setup(requested_model: str) -> str:
    cfg = load_config()

    # ── Try Ollama ────────────────────────────────────────────────────────────
    ollama_models = get_ollama_models()

    if ollama_models is not None:
        if ollama_models:
            activate_ollama(ollama_models)
            return pick_model(requested_model, ollama_models)

        pull_name = requested_model or FALLBACK_MODEL
        size_hint = _model_size_hint(pull_name)
        print(f'\n{Y}  Ollama is running but no models are installed.{X}')
        print(f'  Recommended starter: {B}{pull_name}{X}{size_hint}\n')
        try:
            ans = input(f'  {Y}Download {pull_name} now? [Y/n]: {X}').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            ans = 'n'
        if ans in ('', 'y', 'yes'):
            if pull_model(pull_name):
                fresh = get_ollama_models() or [pull_name]
                activate_ollama(fresh)
                return pick_model(pull_name, fresh)
        print(f'{D}  Skipping download.{X}\n')

    else:
        print(f'{Y}  Ollama not found at {OLLAMA_BASE}.{X}\n')

    # ── Try Nebius ────────────────────────────────────────────────────────────
    nebius_key = os.environ.get('NEBIUS_API_KEY') or cfg.get('nebius_api_key')
    if nebius_key:
        print(f'{D}  Checking Nebius cloud…{X}')
        nebius_models = get_nebius_models(nebius_key)
        if nebius_models:
            activate_nebius(nebius_key, nebius_models)
            chosen = pick_model(requested_model, nebius_models)
            print(f'{G}  ✓ Nebius connected — {len(nebius_models)} models available{X}\n')
            return chosen
        print(f'{R}  Nebius key found but could not fetch models (bad key?).{X}\n')

    # ── Nothing available ─────────────────────────────────────────────────────
    print(f'  {B}No AI backend detected. Choose an option:{X}\n')
    print(f'  {C}1{X}  Install Ollama  (local, private, free — runs on your machine)')
    print(f'  {C}2{X}  Add Nebius API key  (cloud inference, pay-per-use)')
    print(f'  {C}q{X}  Quit\n')
    try:
        choice = input(f'  {Y}Choice [1/2/q]: {X}').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    if choice == '1':
        print(f'\n{D}  Run these commands to install Ollama:{X}')
        print(f'  curl -fsSL https://ollama.com/install.sh | sh')
        print(f'  ollama pull {FALLBACK_MODEL}')
        print(f'\n  Then run {B}draco{X} again.\n')
        sys.exit(0)
    elif choice == '2':
        key = prompt_nebius_credentials()
        if key:
            nebius_models = get_nebius_models(key)
            if nebius_models:
                activate_nebius(key, nebius_models)
                chosen = pick_model(requested_model, nebius_models)
                print(f'{G}  ✓ Nebius connected — {len(nebius_models)} models available{X}\n')
                return chosen
            print(f'{R}  Could not connect to Nebius with that key.{X}\n')

    sys.exit(1)

def _model_size_hint(name: str) -> str:
    n = name.lower()
    if '0.5b' in n or '1b' in n: return ' (~700 MB)'
    if '1.5b' in n:               return ' (~1 GB)'
    if '2b'   in n:               return ' (~1.5 GB)'
    if '3b'   in n:               return ' (~2 GB)'
    if '7b'   in n:               return ' (~4.7 GB)'
    if '8b'   in n:               return ' (~5 GB)'
    if '13b'  in n:               return ' (~8 GB)'
    if '14b'  in n:               return ' (~9 GB)'
    if '32b'  in n:               return ' (~20 GB)'
    if '70b'  in n:               return ' (~40 GB)'
    return ''


# ── Tools ─────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are Draco, a powerful AI agent running directly on the user's machine.
Your name is Draco. You are not ChatGPT, not GPT-4, not Claude — you are Draco.
You have full tool access: run any shell command, read/write any file, list directories.
OS: {os}
Shell: {shell}
Current working directory: {cwd}
Home directory: {home}
Hostname: {hostname}

Rules:
- Be direct and action-oriented. When a task requires system access, use your tools immediately — don't describe what you would do, just do it.
- For simple factual questions, answer directly without calling tools.
- Chain multiple tool calls to complete tasks end-to-end.
- For destructive actions (deleting files, etc.), briefly state what you're about to do before doing it.
- Use shell commands appropriate for the user's OS."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command on the user's machine. Returns stdout, stderr, exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "working_dir": {"type": "string", "description": "Optional working directory"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file's contents.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and subdirectories at a path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"]
            }
        }
    }
]

TOOL_ICONS = {
    'run_command':    '⚡',
    'read_file':      '📄',
    'write_file':     '✏️',
    'list_directory': '📁',
}

_KNOWN_TOOLS = {t['function']['name'] for t in TOOLS}


# ── Tool execution ────────────────────────────────────────────────────────────

def execute_tool(name, args, cwd):
    try:
        if name == 'run_command':
            cmd = args.get('command', '')
            wd  = os.path.expanduser(args.get('working_dir') or cwd)
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=wd, timeout=120,
                env={**os.environ, 'HOME': str(Path.home())} if sys.platform != 'win32' else None
            )
            out = result.stdout
            err = result.stderr
            combined = out
            if err:
                combined += ('\n[stderr]\n' if out else '') + err
            return (combined.strip() or f'(exit {result.returncode})'), result.returncode != 0

        elif name == 'read_file':
            path = _resolve(args.get('path', ''), cwd)
            return Path(path).read_text(encoding='utf-8', errors='replace'), False

        elif name == 'write_file':
            path    = _resolve(args.get('path', ''), cwd)
            content = args.get('content', '')
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding='utf-8')
            return f'Written {len(content)} bytes → {path}', False

        elif name == 'list_directory':
            path = _resolve(args.get('path', cwd), cwd)
            p    = Path(path)
            if not p.exists():
                return f'Not found: {path}', True
            lines = []
            for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name)):
                try:
                    tag  = '📁' if item.is_dir() else '📄'
                    size = f'  {item.stat().st_size:>9,} B' if item.is_file() else ''
                    lines.append(f'{tag} {item.name}{size}')
                except PermissionError:
                    lines.append(f'🔒 {item.name}')
            return ('\n'.join(lines) if lines else '(empty)'), False

        else:
            return f'Unknown tool: {name}', True

    except subprocess.TimeoutExpired:
        return 'Timed out (120 s)', True
    except Exception as e:
        return f'Error: {e}', True


def _resolve(path, cwd):
    path = os.path.expanduser(path)
    return path if os.path.isabs(path) else os.path.join(cwd, path)


# ── JSON tool-call fallback ───────────────────────────────────────────────────
# Some local models output tool calls as JSON in code fences rather than using
# the structured API. This parser catches those and executes them anyway.

def _extract_text_tool_calls(content: str) -> list:
    calls = []
    seen  = set()
    dec   = json.JSONDecoder()

    def _try_add(obj):
        name = obj.get('name')
        if name not in _KNOWN_TOOLS:
            return
        args = obj.get('arguments') or obj.get('parameters') or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        calls.append({
            'id': f'text_call_{len(calls)}',
            'function': {'name': name, 'arguments': json.dumps(args)},
        })

    # Fenced code blocks first
    for block in re.findall(r'```(?:json)?\s*([\s\S]*?)```', content):
        block = block.strip()
        if not block or block in seen:
            continue
        seen.add(block)
        try:
            _try_add(json.loads(block))
        except Exception:
            pass

    # Scan for bare JSON objects anywhere in the text
    i = 0
    while i < len(content):
        if content[i] == '{':
            try:
                obj, end = dec.raw_decode(content, i)
                raw = content[i:end]
                if raw not in seen:
                    seen.add(raw)
                    _try_add(obj)
                i = end
                continue
            except json.JSONDecodeError:
                pass
        i += 1

    return calls


# ── LLM call ─────────────────────────────────────────────────────────────────

def call_llm(messages, model, use_tools):
    """
    Call the active backend. Streams text when no tools; non-streaming when
    tools are active (Ollama streaming + tool calls is unreliable).
    Returns (content: str, tool_calls: list).
    """
    payload = {
        'model':       model,
        'messages':    messages,
        'temperature': 0.7,
        'stream':      not use_tools,
    }
    if use_tools:
        payload['tools']       = TOOLS
        payload['tool_choice'] = 'auto'

    def _post(p):
        return requests.post(
            _chat_url, headers=_headers,
            json=p, stream=p.get('stream', False), timeout=180
        )

    try:
        resp = _post(payload)
        if resp.status_code == 400 and use_tools:
            print(f'\n{Y}  Model doesn\'t support tool use — retrying without tools.{X}')
            print(f'{D}  Pull a tool-capable model: /pull qwen2.5-coder:7b{X}\n')
            payload.pop('tools', None)
            payload.pop('tool_choice', None)
            payload['stream'] = True
            resp      = _post(payload)
            use_tools = False
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        print(f'\n{R}Cannot connect to {_backend} backend.{X}')
        if _backend == 'ollama':
            print(f'{D}Check: systemctl status ollama{X}\n')
        return None, []
    except Exception as e:
        print(f'\n{R}Error: {e}{X}\n')
        return None, []

    # ── Non-streaming (tool-use) path ─────────────────────────────────────────
    if not payload.get('stream'):
        data      = resp.json()
        message   = data.get('choices', [{}])[0].get('message', {})
        content   = message.get('content') or ''
        raw_calls = message.get('tool_calls') or []
        if content:
            print(f'\n{P}{B}Draco:{X} {content}\n')
        tool_calls = [
            {
                'id': tc.get('id', f'call_{i}'),
                'function': {
                    'name':      tc['function']['name'],
                    'arguments': tc['function'].get('arguments', '{}'),
                }
            }
            for i, tc in enumerate(raw_calls)
            if tc.get('function', {}).get('name')
        ]
        return content, tool_calls

    # ── Streaming (no-tools) path ─────────────────────────────────────────────
    content        = ''
    printed_header = False

    for raw in resp.iter_lines():
        if not raw:
            continue
        line = raw.decode('utf-8')
        if line.startswith('data: '):
            line = line[6:]
        if line.strip() == '[DONE]':
            break
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue

        tok = chunk.get('choices', [{}])[0].get('delta', {}).get('content') or ''
        if tok:
            if not printed_header:
                print(f'\n{P}{B}Draco:{X} ', end='', flush=True)
                printed_header = True
            print(tok, end='', flush=True)
            content += tok

    if printed_header:
        print('\n')

    return content, []


# ── Permission prompt ─────────────────────────────────────────────────────────

def ask_permission(name, args, skip):
    icon    = TOOL_ICONS.get(name, '🔩')
    preview = (args.get('command') or args.get('path') or json.dumps(args))[:100]
    print(f'{P}{B}{icon} {name}{X}{D}({preview}){X}')
    if skip:
        return True
    try:
        ans = input(f'{Y}  Allow? [Y/n/d(etails)]: {X}').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if ans == 'd':
        print(f'{D}{json.dumps(args, indent=2)}{X}')
        try:
            ans = input(f'{Y}  Allow? [Y/n]: {X}').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
    return ans in ('', 'y', 'yes')


def print_result(text, is_error):
    color = R if is_error else C
    lines = text.split('\n')
    for line in lines[:40]:
        print(f'  {color}⎿ {D}{line}{X}')
    if len(lines) > 40:
        print(f'  {D}  … {len(lines)-40} more lines{X}')


# ── One conversation turn ─────────────────────────────────────────────────────

def run_turn(messages, model, use_tools, skip, cwd, max_steps=20):
    for step in range(max_steps):
        if step > 0:
            sys.stdout.write(f'{D}  thinking…{X}')
            sys.stdout.flush()

        content, tool_calls = call_llm(messages, model, use_tools)

        if step > 0:
            sys.stdout.write('\r' + ' ' * 20 + '\r')
            sys.stdout.flush()

        if content is None:
            return

        # Fallback: if the model printed tool calls as JSON text instead of
        # using the structured API, parse and execute them.
        if not tool_calls and content and use_tools:
            tool_calls = _extract_text_tool_calls(content)
            if tool_calls:
                print(f'{D}  (parsed {len(tool_calls)} tool call(s) from response text){X}')

        if not tool_calls:
            if content:
                messages.append({'role': 'assistant', 'content': content})
            return

        messages.append({'role': 'assistant', 'content': content or '', 'tool_calls': [
            {'id': tc['id'], 'type': 'function', 'function': tc['function']}
            for tc in tool_calls
        ]})

        for tc in tool_calls:
            name = tc['function']['name']
            try:
                args = json.loads(tc['function']['arguments'] or '{}')
            except Exception:
                args = {}
            print()
            allowed = ask_permission(name, args, skip)
            if not allowed:
                result, is_error = 'User denied this tool call.', False
            else:
                result, is_error = execute_tool(name, args, cwd)
                print_result(result, is_error)
            messages.append({
                'role':         'tool',
                'tool_call_id': tc['id'],
                'name':         name,
                'content':      result
            })

    print(f'{Y}  Max steps reached.{X}')


# ── REPL commands ─────────────────────────────────────────────────────────────

def cmd_models():
    if _backend == 'ollama':
        local = get_ollama_models()
        if local is None:
            print(f'{R}  Ollama unreachable{X}')
            return
        for m in local:
            print(f'  {m}')
    else:
        for m in _models:
            print(f'  {m}')

def cmd_backend_switch(target: str, requested_model: str) -> str:
    global _models
    cfg = load_config()
    if target == 'ollama':
        local = get_ollama_models()
        if local is None:
            print(f'{R}  Ollama not reachable at {OLLAMA_BASE}{X}')
            return requested_model
        if not local:
            print(f'{Y}  Ollama is running but no models installed.{X}')
            return requested_model
        activate_ollama(local)
        new_model = pick_model(requested_model, local)
        print(f'{G}  ✓ Switched to Ollama  ({len(local)} models){X}')
        return new_model
    elif target == 'nebius':
        key = os.environ.get('NEBIUS_API_KEY') or cfg.get('nebius_api_key')
        if not key:
            key = prompt_nebius_credentials()
        if not key:
            return requested_model
        models = get_nebius_models(key)
        if not models:
            print(f'{R}  Could not fetch Nebius models — check your key.{X}')
            return requested_model
        activate_nebius(key, models)
        new_model = pick_model(requested_model, models)
        print(f'{G}  ✓ Switched to Nebius  ({len(models)} models)  model → {new_model}{X}')
        return new_model
    else:
        print(f'{R}  Unknown backend "{target}". Use: ollama | nebius{X}')
        return requested_model

def cmd_pull(model_name: str):
    if _backend != 'ollama':
        print(f'{Y}  /pull only works with Ollama backend{X}')
        return
    try:
        ans = input(f'  {Y}Download {model_name}{_model_size_hint(model_name)}? [Y/n]: {X}').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if ans in ('', 'y', 'yes'):
        if pull_model(model_name):
            fresh = get_ollama_models() or _models + [model_name]
            activate_ollama(fresh)


# ── Main ─────────────────────────────────────────────────────────────────────

HELP_TEXT = f"""
{P}{B}Commands:{X}
  {B}/clear{X}              clear conversation history
  {B}/model <name>{X}       switch model (must be in /models list)
  {B}/models{X}             list available models on current backend
  {B}/backend ollama{X}     switch to local Ollama inference
  {B}/backend nebius{X}     switch to Nebius cloud inference
  {B}/pull <model>{X}       download an Ollama model  (e.g. /pull llama3.2:3b)
  {B}/credentials{X}        set or update Nebius API key
  {B}/docker{X}             install / configure Docker step by step
  {B}/exit{X}               quit
  {B}Ctrl+C{X}              quit (or interrupt current response)
"""

def main():
    ap = argparse.ArgumentParser(
        prog='draco',
        description='Draco — local AI agent with full system access',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  draco                                     interactive session
  draco --model qwen2.5-coder:7b            pick a model
  draco --dangerously-skip-permissions      auto-approve all tool calls
  echo "what is in my Downloads?" | draco   pipe a single prompt
  draco "show me what is running on port 5150"
"""
    )
    ap.add_argument('prompt', nargs='?', help='Single prompt (non-interactive)')
    ap.add_argument('--model', '-m', default=DEFAULT_MODEL,
                    help=f'Model name (default: {DEFAULT_MODEL})')
    ap.add_argument('--dangerously-skip-permissions', action='store_true',
                    help='Auto-approve all tool calls without prompting')
    ap.add_argument('--no-tools', action='store_true', help='Disable tool use')
    ap.add_argument('--models', action='store_true', help='List available models and exit')
    args = ap.parse_args()

    if args.models:
        models = get_ollama_models()
        if models is None:
            print(f'{R}  Ollama unreachable{X}')
            sys.exit(1)
        for m in models:
            marker = f' {G}← default{X}' if m.startswith('qwen2.5-coder:7b') else ''
            print(f'  {m}{marker}')
        sys.exit(0)

    skip      = args.dangerously_skip_permissions
    use_tools = not args.no_tools
    cwd       = os.getcwd()

    print(f'\n{P}{B}  ╔═══════════════════════════════╗')
    print(f'  ║  🐉  Draco  ·  local AI agent  ║')
    print(f'  ╚═══════════════════════════════╝{X}')

    model = setup(args.model)

    backend_label = f'{C}☁  Nebius{X}' if _backend == 'nebius' else f'{G}⬡  Ollama (local){X}'
    print(f'{D}  Backend : {X}{backend_label}')
    print(f'{D}  Model   : {model}')
    print(f'  cwd     : {cwd}')
    if skip:
        print(f'{Y}  ⚠  --dangerously-skip-permissions  (all tool calls auto-approved){X}')
    else:
        print(f'{D}  Tools   : confirm each call   (skip with --dangerously-skip-permissions){X}')

    docker_status = check_docker()
    docker_labels = {
        'ok':            f'{G}✓ running{X}',
        'not_running':   f'{Y}installed but not running{X}  {D}→ /docker to fix{X}',
        'no_permission': f'{Y}installed — need group permission{X}  {D}→ /docker to fix{X}',
        'not_installed': f'{R}not installed{X}  {D}→ /docker to set up{X}',
    }
    print(f'{D}  Docker  : {X}{docker_labels.get(docker_status, docker_status)}')
    print(f'{D}  /help  /models  /pull  /backend  /credentials  /docker  /exit{X}\n')

    _os    = platform.system()
    _shell = 'PowerShell/cmd' if _os == 'Windows' else os.environ.get('SHELL', 'bash')
    system = SYSTEM_PROMPT.format(
        os=_os, shell=_shell,
        cwd=cwd, home=str(Path.home()), hostname=platform.node()
    )
    messages = [{'role': 'system', 'content': system}]

    if args.prompt:
        messages.append({'role': 'user', 'content': args.prompt})
        run_turn(messages, model, use_tools, skip, cwd)
        return

    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            messages.append({'role': 'user', 'content': piped})
            run_turn(messages, model, use_tools, skip, cwd)
        return

    while True:
        try:
            user_input = input(f'{P}{B}draco>{X} ').strip()
        except (KeyboardInterrupt, EOFError):
            print(f'\n{D}Goodbye.{X}\n')
            sys.exit(0)

        if not user_input:
            continue

        if user_input.startswith('/'):
            parts = user_input.split()
            cmd   = parts[0].lower()

            if cmd in ('/exit', '/quit', '/q'):
                print(f'\n{D}Goodbye.{X}\n')
                sys.exit(0)

            elif cmd == '/clear':
                messages = [{'role': 'system', 'content': system}]
                print(f'{G}✓ Conversation cleared.{X}')

            elif cmd == '/help':
                print(HELP_TEXT)

            elif cmd == '/model':
                if len(parts) > 1:
                    model = MODEL_ALIASES.get(parts[1], parts[1])
                    print(f'{G}✓ Model → {model}{X}')
                else:
                    print(f'  Current: {B}{model}{X}  (backend: {_backend})')
                    print(f'{D}  Aliases: ' + '  '.join(f'{k}={v}' for k, v in MODEL_ALIASES.items()) + X)

            elif cmd == '/models':
                backend_label = 'Nebius' if _backend == 'nebius' else 'Ollama'
                print(f'\n{D}  {backend_label} models:{X}')
                cmd_models()
                print()

            elif cmd == '/backend':
                if len(parts) < 2:
                    print(f'  Active: {B}{_backend}{X}   Use: /backend ollama | /backend nebius')
                else:
                    model = cmd_backend_switch(parts[1], model)

            elif cmd == '/pull':
                if len(parts) < 2:
                    print(f'  Usage: /pull <model-name>   e.g. /pull llama3.2:3b')
                else:
                    cmd_pull(parts[1])

            elif cmd == '/docker':
                run_docker_setup()

            elif cmd == '/credentials':
                key = prompt_nebius_credentials()
                if key and _backend == 'nebius':
                    new_models = get_nebius_models(key)
                    if new_models:
                        activate_nebius(key, new_models)
                        print(f'{G}✓ Nebius refreshed — {len(new_models)} models{X}')

            else:
                print(f'{R}Unknown: {cmd}{X}  — type /help')
            continue

        messages.append({'role': 'user', 'content': user_input})
        run_turn(messages, model, use_tools, skip, cwd)


if __name__ == '__main__':
    main()
