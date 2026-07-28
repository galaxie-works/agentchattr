"""Run one AgentChattr member backed by one persisted provider session.

The worker is a local adapter: it consumes only its own AgentChattr queue,
uses the configured provider's resume command with one explicit target, and
posts the final agent message back as a reply. It does not read provider
session files or accept a target from chat input.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from config_loader import apply_cli_overrides, load_config
from thread_relays import ThreadRelays
from wrapper import _auth_headers, _register_instance


ROOT = Path(__file__).parent


def build_turn_prompt(entry: dict) -> str:
    """Build an explicit, correlated relay turn without inventing a sender."""
    channel = str(entry.get("channel", "general"))
    message_id = entry.get("message_id", "unknown")
    # ``codex exec resume`` uses the first physical line of its prompt for a
    # resumed turn on Windows. Preserve all user content while keeping the
    # relay input to one line.
    text = " ".join(str(entry.get("text", "")).split())
    return (
        f"ROOM MESSAGE #{message_id} in #{channel}: {text}. "
        "You are responding through an AgentChattr room relay. "
        "Answer the substantive request below directly and concisely. Your final "
        "answer will be posted verbatim back to the room as a reply. Do not claim "
        "to have sent a room message yourself, do not change relay configuration, "
        "and do not use tools unless the request genuinely needs them. "
        "If you need another room member, include its exact @mention in your final answer."
    )


def extract_final_message(stdout: str, provider: str = "codex") -> str:
    """Return the final provider response from its machine-readable output."""
    if provider == "claude":
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return ""
        result = payload.get("result")
        return result.strip() if isinstance(result, str) else ""

    result = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                result = text.strip()
    return result


def run_turn(relay, prompt: str) -> tuple[str, str]:
    """Resume the configured provider target using its local CLI."""
    executable = shutil.which(relay.command)
    if not executable:
        return "", f"{relay.provider.title()} command {relay.command!r} was not found on PATH."
    if not relay.cwd.is_dir():
        return "", f"Configured relay directory does not exist: {relay.cwd}"

    if relay.provider == "claude":
        args = [
            executable, "--print", "--output-format", "json", "--resume", relay.session_id,
            "--dangerously-skip-permissions", prompt,
        ]
    else:
        args = [
            executable, "exec", "--json", "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check", "resume",
            relay.session_id, prompt,
        ]
    try:
        completed = subprocess.run(
            args,
            cwd=relay.cwd,
            env=os.environ.copy(),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=relay.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return "", f"Timed out after {relay.timeout_seconds}s while waiting for the {relay.provider} relay."
    except OSError as exc:
        return "", f"Could not start {relay.provider}: {exc}"

    final = extract_final_message(completed.stdout, relay.provider)
    if final:
        return final, ""
    detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "no final agent message"
    return "", f"{relay.provider.title()} relay exited with code {completed.returncode}: {detail}"


def _post(url: str, token: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers=_auth_headers(token, include_json=True),
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def _heartbeat_loop(server_port: int, identity: dict, lock: threading.Lock, stop: threading.Event):
    while not stop.wait(5):
        with lock:
            name, token, active = identity["name"], identity["token"], identity["active"]
        try:
            _post(
                f"http://127.0.0.1:{server_port}/api/heartbeat/{name}",
                token,
                {"active": active},
            )
        except Exception:
            pass


def _drain_queue(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    lines = path.read_text("utf-8").splitlines()
    path.write_text("", "utf-8")
    entries = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("text"):
            entries.append(item)
    return entries


def main() -> int:
    apply_cli_overrides()
    config = load_config(ROOT)
    configured = ThreadRelays(config.get("thread_relays"), set(
        name for name, cfg in config.get("agents", {}).items() if cfg.get("type") != "thread_relay"
    ), ROOT)
    parser = argparse.ArgumentParser(description="Bridge an AgentChattr member to a persisted provider session")
    parser.add_argument("agent", choices=configured.names, help="Configured thread relay to run")
    parser.add_argument("--no-restart", action="store_true", help="Exit if the server cannot be reached")
    args = parser.parse_args()
    relay = configured.get(args.agent)
    assert relay is not None

    server_port = config.get("server", {}).get("port", 8300)
    data_dir = Path(config.get("server", {}).get("data_dir", "./data"))
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    from worker_singleton import WorkerAlreadyRunning, acquire_worker_lock

    try:
        worker_lock = acquire_worker_lock(relay.name, data_dir)
    except WorkerAlreadyRunning:
        print(f"Thread relay @{relay.name} is already running; duplicate launch ignored.")
        return 0

    try:
        registration = _register_instance(server_port, relay.name, relay.label)
    except Exception as exc:
        print(f"Registration failed: {exc}")
        return 1
    identity = {"name": registration["name"], "token": registration["token"], "active": False}
    identity_lock = threading.Lock()
    queue_file = data_dir / f"{identity['name']}_queue.jsonl"
    print(f"Thread relay @{identity['name']} -> {relay.provider}:{relay.session_id}")

    stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(server_port, identity, identity_lock, stop), daemon=True
    )
    heartbeat.start()
    try:
        while True:
            for entry in _drain_queue(queue_file):
                with identity_lock:
                    identity["active"] = True
                    name, token = identity["name"], identity["token"]
                answer, error = run_turn(relay, build_turn_prompt(entry))
                with identity_lock:
                    identity["active"] = False
                text = answer if answer else f"[thread relay error] {error}"
                payload = {
                    "text": text,
                    "channel": entry.get("channel", "general"),
                    "reply_to": entry.get("message_id"),
                }
                try:
                    _post(f"http://127.0.0.1:{server_port}/api/send", token, payload)
                except Exception as exc:
                    print(f"Failed to post relay response: {exc}", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 0
    finally:
        stop.set()
        with identity_lock:
            name, token = identity["name"], identity["token"]
        try:
            _post(f"http://127.0.0.1:{server_port}/api/deregister/{name}", token, {})
        except Exception:
            pass
        worker_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
