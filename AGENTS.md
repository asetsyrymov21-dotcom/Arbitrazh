# AGENTS.md

## Secret handling — mandatory

- Never commit or push real API keys, access tokens, passwords, private keys, credential URLs, or production configuration.
- Keep secrets in ignored local environment files or the GitHub Actions secrets store. Example/template files must contain placeholders only.
- Before every commit, scan the staged diff with Gitleaks using --pre-commit --staged --redact=100.
- Before every push or PR, scan every commit being published with Gitleaks using --log-opts=--all --redact=100.
- If the scanner is missing, fails, or finds a secret, stop. Never use --no-verify, bypass push protection, or add an allowlist to conceal a real secret.
- Stage explicit paths only. Never stage .env files, key files, private credential backups, or cleanup bundles.
- Never print secret values in logs, commands, reviews, screenshots, or PR descriptions.
- If a secret was committed, remove it from reachable history and report that revocation/rotation and GitHub cache/PR cleanup may still be required.
