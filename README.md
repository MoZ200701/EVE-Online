# EVE Market Tool

A local market trading helper for EVE Online. The first milestone is only the project scaffold and configuration wiring; data ingestion and analytics arrive in later milestones.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Edit `config.toml` and replace the `REPLACE_ME` contact placeholder in `user_agent` before using live ESI endpoints in later milestones.

```powershell
evemarket info
evemarket info --config config.toml
```

## Agent Workflow

This project uses a two-agent workflow documented in `HANDOFF.md`: Claude plans, debugs, and reviews; GPT-5.5 Codex executes the current task, verifies it, and reports back in the execution log. Agents should read `HANDOFF.md` before acting and should advance one milestone at a time.

