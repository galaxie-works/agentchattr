"""
discover_threads.py — descoberta dinâmica de threads/sessões dos agentes locais.

Objetivo: o stepper de "criar sala" precisa listar as CONVERSAS EXISTENTES de cada
agente (sem lista fixa) para o usuário linkar uma thread na "nossa arquitetura
customizada" (relay que resume/endereça a conversa que já existe, com contexto).

⚠️ Nem todo agente tem "conversa existente endereçável". O modelo padrão do
agentchattr é **spawnar um processo novo** (app-level). Só alguns provedores
expõem como resumir/endereçar uma conversa que já existe:

  - claude → `claude --resume <id>` (id = nome do transcript ~/.claude/projects/<proj>/<id>.jsonl).
             ⚠️ NÃO use ids `local_<uuid>` de outras APIs — não batem com --resume.
  - codex  → thread do Codex Desktop, endereçada por thread_id via thread_relay
             (id = campo `id` de ~/.codex/session_index.jsonl).

Os demais (gemini, copilot, kimi, qwen, kilo, codebuddy, minimax) hoje são
`resumable=False` (app-level = processo novo). Quando alguém descobrir o store de
sessão de um deles, é só preencher o `discover` na PROVIDERS — a UI se adapta
sozinha pela flag `resumable` (não precisa mexer no stepper).

API para o servidor (app.py):
    from discover_threads import providers, discover, discover_all
    providers()            # manifesto: [{name,label,resumable,address,store_hint}]
    discover("claude")     # threads de um provedor  -> list[dict]
    discover_all()         # {provider: list[dict]} (não-resumable vêm [])

CLI:
    python discover_threads.py --providers          # capability de cada agente
    python discover_threads.py --provider claude
    python discover_threads.py --provider all --limit 20

Cada thread: {provider, id, name, cwd, git_branch, last_activity, relay_bot?}
Multiplataforma (Windows/macOS/Linux). Só stdlib.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_MAX_HEAD_LINES = 40   # linhas do transcript a ler p/ achar nome/cwd (ficam no começo)
_NAME_MAXLEN = 80


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _first_text(content) -> str | None:
    if isinstance(content, str):
        return content.strip() or None
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = (block.get("text") or "").strip()
                if t:
                    return t
    return None


def _clip(name: str | None) -> str | None:
    if not name:
        return None
    name = name.replace("\n", " ").strip()
    return name if len(name) <= _NAME_MAXLEN else name[: _NAME_MAXLEN - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# claude — ~/.claude/projects/<proj>/<id>.jsonl  (resumível por --resume <id>)
# ---------------------------------------------------------------------------
def _claude_meta(transcript: Path) -> tuple[str | None, str | None, str | None]:
    name = cwd = branch = None
    try:
        with transcript.open("r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= _MAX_HEAD_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if cwd is None and isinstance(d.get("cwd"), str):
                    cwd = d["cwd"]
                if branch is None and isinstance(d.get("gitBranch"), str):
                    branch = d["gitBranch"] or None
                if name is None and d.get("type") == "summary" and d.get("summary"):
                    name = str(d["summary"]).strip()
                if name is None:
                    role = d.get("type") or (d.get("message") or {}).get("role")
                    if role == "user":
                        msg = d.get("message") or d
                        txt = _first_text(msg.get("content"))
                        if txt and not txt.startswith("[") and "tool_result" not in txt:
                            name = txt
                if name and cwd and branch:
                    break
    except Exception:
        pass
    return _clip(name), cwd, (branch if branch and branch != "HEAD" else None)


def discover_claude_threads(claude_home: Path | None = None) -> list[dict]:
    base = (claude_home or (Path.home() / ".claude")) / "projects"
    out: list[dict] = []
    if not base.is_dir():
        return out
    for proj in base.iterdir():
        if not proj.is_dir():
            continue
        for tr in proj.glob("*.jsonl"):
            try:
                st = tr.stat()
            except OSError:
                continue
            if st.st_size == 0:
                continue
            name, cwd, branch = _claude_meta(tr)
            out.append({
                "provider": "claude",
                "id": tr.stem,                       # id do --resume
                "name": name or (Path(cwd).name if cwd else tr.stem),
                "cwd": cwd,
                "git_branch": branch,
                "last_activity": _iso(st.st_mtime),
                # sessões spawnadas pelo próprio wrapper começam com o prompt de
                # injeção — a UI normalmente as esconde da lista de "linkar".
                "relay_bot": bool(name and name.startswith("use mcp to read #")),
            })
    out.sort(key=lambda t: t["last_activity"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# codex — ~/.codex/session_index.jsonl  (thread do Desktop, endereçada por thread_id)
# ---------------------------------------------------------------------------
def discover_codex_threads(codex_home: Path | None = None) -> list[dict]:
    idx = (codex_home or (Path.home() / ".codex")) / "session_index.jsonl"
    latest: dict[str, dict] = {}
    if not idx.is_file():
        return []
    try:
        with idx.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                tid = d.get("id")
                if not tid:
                    continue
                upd = d.get("updated_at") or ""
                prev = latest.get(tid)
                if prev is None or upd >= prev["last_activity"]:
                    latest[tid] = {
                        "provider": "codex",
                        "id": tid,                    # thread_id do thread_relay
                        "name": _clip(d.get("thread_name")) or tid,
                        "cwd": d.get("cwd"),
                        "git_branch": None,
                        "last_activity": upd,
                    }
    except Exception:
        pass
    out = list(latest.values())
    out.sort(key=lambda t: t["last_activity"], reverse=True)
    return out


def _none(*_a, **_k) -> list[dict]:
    """Provedores sem descoberta implementada (usam app-level = processo novo)."""
    return []


# ---------------------------------------------------------------------------
# REGISTRY — mesma lista de provedores do agentchattr (wrapper._BUILTIN_DEFAULTS
# + os do README). Adicionar/ligar um agente = uma entrada aqui; a UI se adapta
# pela flag `resumable`.
# ---------------------------------------------------------------------------
PROVIDERS: dict[str, dict] = {
    "claude": {
        "label": "Claude Code",
        "resumable": True,
        "discover": discover_claude_threads,
        "address": "claude --resume <id>  (rodar no cwd da sessão)",
        "store_hint": "~/.claude/projects/<proj>/<id>.jsonl",
    },
    "codex": {
        "label": "Codex",
        "resumable": True,
        "discover": discover_codex_threads,
        "address": "thread_relay por thread_id (Codex Desktop)",
        "store_hint": "~/.codex/session_index.jsonl",
    },
    # --- resumível ainda NÃO implementado: hoje app-level (processo novo). ---
    "gemini": {"label": "Gemini CLI", "resumable": False, "discover": _none,
               "address": "processo novo (app-level)",
               "store_hint": "TODO — provável ~/.gemini/ (checkpoints); não verificado"},
    "copilot": {"label": "GitHub Copilot CLI", "resumable": False, "discover": _none,
                "address": "processo novo (app-level)",
                "store_hint": "TODO — não verificado"},
    "kimi": {"label": "Kimi", "resumable": False, "discover": _none,
             "address": "processo novo (app-level)", "store_hint": "TODO — não verificado"},
    "qwen": {"label": "Qwen", "resumable": False, "discover": _none,
             "address": "processo novo (app-level)",
             "store_hint": "TODO — provável ~/.qwen/ (fork do gemini-cli); não verificado"},
    "kilo": {"label": "Kilo CLI", "resumable": False, "discover": _none,
             "address": "processo novo (app-level)", "store_hint": "TODO — não verificado"},
    "codebuddy": {"label": "CodeBuddy", "resumable": False, "discover": _none,
                  "address": "processo novo (app-level)", "store_hint": "TODO — não verificado"},
    "minimax": {"label": "MiniMax", "resumable": False, "discover": _none,
                "address": "processo novo (app-level)", "store_hint": "TODO — não verificado"},
}


def providers() -> list[dict]:
    """Manifesto de capability por provedor (a UI decide se mostra o passo de linkar)."""
    return [
        {"name": n, "label": s["label"], "resumable": s["resumable"],
         "address": s["address"], "store_hint": s["store_hint"]}
        for n, s in PROVIDERS.items()
    ]


def discover(provider: str) -> list[dict]:
    spec = PROVIDERS.get(provider)
    return spec["discover"]() if spec else []


def discover_all() -> dict[str, list[dict]]:
    return {n: s["discover"]() for n, s in PROVIDERS.items()}


# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    import argparse
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # CLI sempre UTF-8 limpo
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Descobre threads locais dos agentes.")
    p.add_argument("--provider", default="all", help="claude|codex|<agente>|all")
    p.add_argument("--providers", action="store_true", help="lista o manifesto de capability")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args(argv)

    if args.providers:
        data: object = providers()
    elif args.provider == "all":
        data = discover_all()
    else:
        data = discover(args.provider)

    if args.limit and isinstance(data, list):
        data = data[: args.limit]
    elif args.limit and isinstance(data, dict):
        data = {k: (v[: args.limit] if isinstance(v, list) else v) for k, v in data.items()}

    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
