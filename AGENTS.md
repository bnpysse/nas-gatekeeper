# Workspace Rules & User Preferences

## Shell & Environment
- **Shell**: The user uses **Fish Shell** (`fish`).
- When providing shell commands, scripts, or instructions in responses:
  - Provide syntax compatible with Fish Shell.
  - For Python virtual environments, use `source <venv>/bin/activate.fish`.
  - For setting environment variables, use `set -gx KEY value` or `set -x KEY value` instead of `export KEY=value` (or explain both if needed).
