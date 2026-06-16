## Learned User Preferences
- Prefer atomic local git commits at clear task/phase boundaries.
- When CLI arguments are missing, prompt interactively with sensible defaults (press Enter accepts defaults).
- Avoid silent failures; surface robust, user-facing error messages (include vendor/status context where relevant).
- For third-party API schema issues, prefer pulling current docs (e.g., via Context7) before updating integrations.

## Learned Workspace Facts
- `TradingAgents` has an interactive CLI/Rich TUI flow (menus via `questionary`, rendering via `rich`).
- The project includes backtesting and paper trading modes that depend on live crypto data vendors and can fall back when APIs fail.
