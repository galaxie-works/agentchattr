"""Shared config loader — merges config.toml + config.local.toml.

Used by run.py, wrapper.py, and wrapper_api.py so the server and all
wrappers see the same agent definitions.

Per-invocation overrides: the following environment variables, if set,
override values from config.toml. This lets dotfiles/launcher layers run
isolated instances per project without editing the repo's config file.

  AGENTCHATTR_DATA_DIR        → server.data_dir
  AGENTCHATTR_PORT            → server.port           (int)
  AGENTCHATTR_MCP_HTTP_PORT   → mcp.http_port         (int)
  AGENTCHATTR_MCP_SSE_PORT    → mcp.sse_port          (int)
  AGENTCHATTR_UPLOAD_DIR      → images.upload_dir

Relative paths in env var overrides resolve against the current working
directory (where the user invoked the command from), not agentchattr's
install directory.
"""

import os
import sys
import tomllib
import json
from pathlib import Path

ROOT = Path(__file__).parent


# Mapping: env var name → (config section, key, is_int)
_ENV_OVERRIDES = [
    ("AGENTCHATTR_DATA_DIR",      "server", "data_dir",   False),
    ("AGENTCHATTR_PORT",          "server", "port",       True),
    ("AGENTCHATTR_MCP_HTTP_PORT", "mcp",    "http_port",  True),
    ("AGENTCHATTR_MCP_SSE_PORT",  "mcp",    "sse_port",   True),
    ("AGENTCHATTR_UPLOAD_DIR",    "images", "upload_dir", False),
]

# Mapping: CLI flag → env var (for apply_cli_overrides)
CLI_OVERRIDE_FLAGS = [
    ("--data-dir",      "AGENTCHATTR_DATA_DIR"),
    ("--port",          "AGENTCHATTR_PORT"),
    ("--mcp-http-port", "AGENTCHATTR_MCP_HTTP_PORT"),
    ("--mcp-sse-port",  "AGENTCHATTR_MCP_SSE_PORT"),
    ("--upload-dir",    "AGENTCHATTR_UPLOAD_DIR"),
]


def apply_cli_overrides(argv: list[str] | None = None) -> None:
    """Scan argv for --data-dir/--port/etc and set matching env vars in-place.

    Called by run.py, wrapper.py, and wrapper_api.py BEFORE load_config() so
    all entry points respect the same overrides when launched with the same
    flags. No effect if a flag isn't present. Supports both `--flag value`
    and `--flag=value` forms.

    Arguments after a literal `--` are treated as pass-through (e.g. for the
    agent CLI in wrapper.py) and are NOT scanned — `python wrapper.py claude
    -- --port 9999` sets `--port 9999` on the agent, not on agentchattr.
    """
    if argv is None:
        argv = sys.argv

    # Truncate at pass-through separator so agent CLI args don't leak in.
    try:
        end = argv.index("--")
        scan = argv[:end]
    except ValueError:
        scan = argv

    for flag, env in CLI_OVERRIDE_FLAGS:
        # Iterate in order; first match wins (ignore later duplicates).
        for i, arg in enumerate(scan):
            if arg == flag and i + 1 < len(scan):
                os.environ[env] = scan[i + 1]
                break
            if arg.startswith(flag + "="):
                os.environ[env] = arg.split("=", 1)[1]
                break


def _apply_env_overrides(config: dict) -> None:
    """Apply AGENTCHATTR_* env vars to the config dict in-place."""
    for env_var, section, key, is_int in _ENV_OVERRIDES:
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        if is_int:
            try:
                value = int(raw)
            except ValueError:
                print(f"  Warning: {env_var}={raw!r} is not a valid integer, ignoring")
                continue
        else:
            # Path values: resolve relative paths against current working dir,
            # not against agentchattr's install directory.
            p = Path(raw)
            if not p.is_absolute():
                p = (Path.cwd() / p).resolve()
            value = str(p)
        config.setdefault(section, {})[key] = value


def _merge_runtime_thread_relays(config: dict, root: Path) -> None:
    """Apply local UI relay targets after TOML without mutating either TOML file."""
    from thread_relays import runtime_relays_path

    path = runtime_relays_path(config, root)
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  Warning: Ignoring invalid runtime thread relays at {path}: {exc}")
        return
    entries = payload.get("thread_relays", payload) if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        print(f"  Warning: Ignoring invalid runtime thread relays at {path}")
        return
    merged = config.setdefault("thread_relays", {})
    for name, relay_cfg in entries.items():
        if isinstance(relay_cfg, dict):
            # An explicit local setting from the UI is deliberately allowed to
            # update the matching local TOML relay after a restart.
            merged[name] = relay_cfg


def _merge_runtime_room_agents(config: dict, root: Path) -> None:
    """Load wizard-created wrapper aliases from ignored local data."""
    from thread_relays import runtime_relays_path

    path = runtime_relays_path(config, root).with_name("room_agents.json")
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  Warning: Ignoring invalid room agents at {path}: {exc}")
        return
    entries = payload.get("agents", payload) if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        print(f"  Warning: Ignoring invalid room agents at {path}")
        return
    agents = config.setdefault("agents", {})
    for name, agent_cfg in entries.items():
        if isinstance(agent_cfg, dict):
            agents[name] = agent_cfg


def load_config(root: Path | None = None) -> dict:
    """Load config.toml and merge config.local.toml if it exists.

    config.local.toml is gitignored and intended for user-specific agents
    (e.g. local LLM endpoints) that shouldn't be committed.
    The [agents], [relays], [projects], and [thread_relays] sections are merged — local entries
    are added alongside (not replacing) entries defined in config.toml.

    AGENTCHATTR_* environment variables override values from config.toml
    (see module docstring for the list).
    """
    root = root or ROOT
    config_path = root / "config.toml"

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    local_path = root / "config.local.toml"
    if local_path.exists():
        with open(local_path, "rb") as f:
            local = tomllib.load(f)

        # Merge [agents] section — local agents are added ONLY if they don't already exist.
        # This protects the "holy trinity" (claude, codex, gemini) from being overridden.
        local_agents = local.get("agents", {})
        config_agents = config.setdefault("agents", {})
        for name, agent_cfg in local_agents.items():
            if name not in config_agents:
                config_agents[name] = agent_cfg
            else:
                print(f"  Warning: Ignoring local agent '{name}' (already defined in config.toml)")

        # Relay aliases are local collaboration wiring. Like agents, a local
        # config may add routes but never silently replace a committed route.
        local_relays = local.get("relays", {})
        config_relays = config.setdefault("relays", {})
        for alias, relay_cfg in local_relays.items():
            if alias not in config_relays:
                config_relays[alias] = relay_cfg
            else:
                print(f"  Warning: Ignoring local relay '{alias}' (already defined in config.toml)")

        # Project registrations are also local machine wiring.  They become
        # isolated agent members only after all local config is merged below.
        local_projects = local.get("projects", {})
        config_projects = config.setdefault("projects", {})
        for name, project_cfg in local_projects.items():
            if name not in config_projects:
                config_projects[name] = project_cfg
            else:
                print(f"  Warning: Ignoring local project '{name}' (already defined in config.toml)")

        local_thread_relays = local.get("thread_relays", {})
        config_thread_relays = config.setdefault("thread_relays", {})
        for name, relay_cfg in local_thread_relays.items():
            if name not in config_thread_relays:
                config_thread_relays[name] = relay_cfg
            else:
                print(f"  Warning: Ignoring local thread relay '{name}' (already defined in config.toml)")

    _apply_env_overrides(config)
    _merge_runtime_thread_relays(config, root)
    _merge_runtime_room_agents(config, root)

    # Project members are generated after overrides/merges so the web server
    # and wrappers use exactly the same provider, CWD, and relay definitions.
    from projects import materialize_projects
    materialize_projects(config, root)
    from thread_relays import materialize_thread_relays
    materialize_thread_relays(config, root)

    return config
