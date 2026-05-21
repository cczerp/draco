#!/usr/bin/env python3
"""
Regression personality tests for Draco.

Tests behavioral parity with Claude CLI — not just function correctness
but response quality: no JSON leakage, no verbose endings, correct tool
routing, preference for direct answers over tool use on factual questions.

Usage:
    python3 tests/personality_test.py
    python3 tests/personality_test.py --model qwen2.5-coder:3b
    python3 tests/personality_test.py --timeout 200 --filter tool

Note: Run sequentially (not in parallel) — Ollama is single-threaded and
parallel test processes share the inference queue, causing unpredictable
latency and occasional model state interference.
"""

import argparse
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

DRACO   = str(Path(__file__).parent.parent / 'draco.py')
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

# ANSI colours for output
G = '\x1b[92m'; R = '\x1b[91m'; Y = '\x1b[93m'; D = '\x1b[2m'; X = '\x1b[0m'; B = '\x1b[1m'

TOOL_ICONS = {'⚡', '📄', '✏️', '📁', '🌐'}


# ── Check types ───────────────────────────────────────────────────────────────

@dataclass
class Check:
    kind: str
    value: str = ''

    @staticmethod
    def response_contains(text: str) -> 'Check':
        return Check('response_contains', text)

    @staticmethod
    def response_not_contains(text: str) -> 'Check':
        return Check('response_not_contains', text)

    @staticmethod
    def response_no_regex(pattern: str) -> 'Check':
        return Check('response_no_regex', pattern)

    @staticmethod
    def output_contains(text: str) -> 'Check':
        return Check('output_contains', text)

    @staticmethod
    def tool_fired() -> 'Check':
        return Check('tool_fired')

    @staticmethod
    def no_tool_fired() -> 'Check':
        return Check('no_tool_fired')

    @staticmethod
    def no_json_in_response() -> 'Check':
        return Check('response_no_regex', r'^\s*\{|\}\s*$')

    @staticmethod
    def no_verbose_endings() -> 'Check':
        return Check('response_no_regex',
                     r'(?i)(feel free|how can i (?:help|assist)|let me know|'
                     r'is there anything|don.t hesitate|hope this helps|'
                     r'reach out if|what else can i)')


# ── Test definition ───────────────────────────────────────────────────────────

@dataclass
class Test:
    name:        str
    prompt:      str
    checks:      List[Check]
    timeout:     int   = 90    # seconds; conversational tests are fast
    tool_timeout: int  = 160   # seconds; tool tests need extra time


# ── Test catalogue ────────────────────────────────────────────────────────────

TESTS: List[Test] = [
    # ── Direct-answer tests (no tools should fire) ────────────────────────────
    Test(
        name    = 'math_direct_answer',
        prompt  = 'what is 17 times 8?',
        checks  = [
            Check.response_contains('136'),
            Check.no_tool_fired(),
            Check.no_json_in_response(),
        ],
    ),
    Test(
        name    = 'factual_capital',
        prompt  = 'what is the capital of Japan?',
        checks  = [
            Check.response_contains('Tokyo'),
            Check.no_tool_fired(),
            Check.no_json_in_response(),
        ],
    ),
    Test(
        name    = 'identity_is_draco',
        prompt  = 'who are you?',
        checks  = [
            Check.response_contains('Draco'),
            Check.response_not_contains('Claude'),
            Check.response_not_contains('Anthropic'),
            Check.no_tool_fired(),
        ],
    ),
    Test(
        name    = 'no_verbose_endings_factual',
        prompt  = 'what is the capital of France?',
        checks  = [
            Check.response_contains('Paris'),
            Check.no_verbose_endings(),
        ],
    ),
    Test(
        name    = 'concept_no_tool',
        prompt  = 'what is the difference between a process and a thread?',
        checks  = [
            Check.no_tool_fired(),
            Check.response_not_contains('⎿'),
        ],
    ),
    # ── JSON / formatting cleanliness ─────────────────────────────────────────
    Test(
        name    = 'no_json_leakage_math',
        prompt  = 'what is 2 + 2?',
        checks  = [
            Check.response_contains('4'),
            Check.no_json_in_response(),
        ],
    ),
    Test(
        name    = 'no_raw_tool_json_in_response',
        prompt  = 'what is the capital of Germany?',
        checks  = [
            Check.response_contains('Berlin'),
            Check.response_no_regex(r'"name"\s*:\s*"'),    # no tool-call JSON
        ],
    ),
    # ── Tool-routing tests (tools MUST fire) ──────────────────────────────────
    Test(
        name     = 'tool_run_command',
        prompt   = 'run: echo draco_personality_test',
        timeout  = 200,
        checks   = [
            Check.tool_fired(),
            Check.output_contains('draco_personality_test'),
        ],
    ),
    Test(
        name     = 'tool_read_file',
        prompt   = 'read /etc/hostname',
        timeout  = 200,
        checks   = [
            Check.tool_fired(),
            Check.output_contains('sassypad'),
        ],
    ),
    Test(
        name     = 'tool_list_directory',
        prompt   = 'list /tmp',
        timeout  = 200,
        checks   = [
            Check.tool_fired(),
            Check.output_contains('⎿'),    # at least one result line
        ],
    ),
    # ── Post-tool response quality ────────────────────────────────────────────
    Test(
        name     = 'tool_result_converted_to_text',
        # Prompt forces the model to read the file and report actual content.
        # A natural-language phrasing (not "read /etc/hostname") ensures the
        # summary step runs rather than being skipped by the single-step heuristic.
        prompt   = 'what hostname does /etc/hostname show right now?',
        timeout  = 200,
        checks   = [
            Check('response_exists'),
            Check.response_contains('sassypad'),
            Check.no_json_in_response(),
            Check.no_verbose_endings(),
        ],
    ),
    Test(
        name     = 'run_result_not_verbose',
        # Use "can you run" so skip-summary heuristic doesn't trigger and
        # the summary LLM call runs — this tests the quality of that response.
        prompt   = 'can you run: echo hello_draco',
        timeout  = 200,
        checks   = [
            Check.tool_fired(),
            Check.output_contains('hello_draco'),
            Check.no_verbose_endings(),
            Check.response_no_regex(r'"name"\s*:'),
        ],
    ),
]


# ── Runner ────────────────────────────────────────────────────────────────────

def run_draco(prompt: str, timeout: int, model: Optional[str]) -> Tuple[str, float, int]:
    cmd = ['python3', DRACO, '--dangerously-skip-permissions', prompt]
    if model:
        cmd += ['--model', model]
    t0 = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = ANSI_RE.sub('', result.stdout)
        return output, time.monotonic() - t0, result.returncode
    except subprocess.TimeoutExpired:
        return '', timeout, -1


def _draco_response(output: str) -> str:
    lines = [l[7:].strip() for l in output.splitlines() if l.startswith('Draco:')]
    return lines[-1] if lines else ''


def _tool_fired_in(output: str) -> bool:
    return any(icon in output for icon in TOOL_ICONS)


def check_output(chk: Check, output: str, response: str) -> Tuple[bool, str]:
    k, v = chk.kind, chk.value
    if k == 'response_contains':
        ok = v.lower() in response.lower()
        return ok, f'response contains {v!r}' if ok else f'response missing {v!r}  (got: {response[:80]!r})'
    if k == 'response_not_contains':
        ok = v.lower() not in response.lower()
        return ok, f'response avoids {v!r}' if ok else f'response leaked {v!r}'
    if k == 'response_no_regex':
        ok = not re.search(v, response, re.IGNORECASE | re.MULTILINE)
        return ok, f'no {v!r} in response' if ok else f'found disallowed pattern {v!r} in response'
    if k == 'output_contains':
        ok = v in output
        return ok, f'output contains {v!r}' if ok else f'output missing {v!r}'
    if k == 'tool_fired':
        ok = _tool_fired_in(output)
        return ok, 'tool fired' if ok else 'no tool fired (expected one)'
    if k == 'no_tool_fired':
        ok = not _tool_fired_in(output)
        return ok, 'no tool fired' if ok else 'tool fired unexpectedly'
    if k == 'response_exists':
        ok = bool(response)
        return ok, 'Draco: response present' if ok else 'no Draco: response line'
    return False, f'unknown check kind: {k!r}'


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='Draco personality regression tests')
    ap.add_argument('--model', '-m', help='Override model')
    ap.add_argument('--filter', '-f', help='Only run tests whose name contains this substring')
    ap.add_argument('--timeout', '-t', type=int, help='Override per-test timeout (seconds)')
    args = ap.parse_args()

    tests = [t for t in TESTS if not args.filter or args.filter in t.name]
    if not tests:
        print(f'{R}No tests match filter {args.filter!r}{X}')
        sys.exit(1)

    print(f'\n{B}Draco personality tests{X}  ({len(tests)} tests)\n')

    passed = failed = 0
    for t in tests:
        timeout = args.timeout or t.timeout
        sys.stdout.write(f'  {D}{t.name:<40}{X}')
        sys.stdout.flush()

        output, elapsed, rc = run_draco(t.prompt, timeout, args.model)
        response = _draco_response(output)

        if rc == -1:
            print(f'{R}TIMEOUT {timeout}s{X}')
            failed += 1
            continue

        failures = []
        for chk in t.checks:
            ok, msg = check_output(chk, output, response)
            if not ok:
                failures.append(msg)

        if failures:
            print(f'{R}FAIL{X}  ({elapsed:.0f}s)')
            for f in failures:
                print(f'      {R}✗{X} {f}')
            failed += 1
        else:
            print(f'{G}PASS{X}  {D}({elapsed:.0f}s){X}')
            passed += 1

    total = passed + failed
    color = G if failed == 0 else R
    print(f'\n  {color}{B}{passed}/{total} passed{X}')
    if failed:
        print(f'  {R}{failed} failed{X}')
    print()
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
