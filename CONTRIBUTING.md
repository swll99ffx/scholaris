# Contributing to Scholaris

Thanks for taking a look at Scholaris. This project is a study assistant with a
React PWA frontend and a FastAPI backend. Module 1 (Research Source Finder) and
Module 2 (Source Summarizer) are built; Modules 3–6 are planned.

## Local setup

Requirements: Python 3.11+ and Node.js 20+.

```powershell
# From the repository root
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

The setup script creates the backend virtualenv, installs dependencies, and
copies `.env.example` to `.env`. See the main [README](README.md) for manual
instructions and phone/LAN testing.

## Tests and build

```powershell
# Backend — offline unit tests, no API keys or network needed
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Frontend — typecheck + production build
cd ..\frontend
npm run typecheck
npm run build
```

CI runs the same backend suite and frontend build on every push and pull
request.

## Secrets

- **Never commit `.env` files or saved library databases.** They are ignored by
  Git, but check `git status` before committing.
- Put real keys only in your local `.env`. Use `.env.example` for new settings
  and placeholder values.
- If a key is accidentally exposed, revoke and rotate it with the provider
  immediately. Removing it in a later commit is not enough — Git history keeps
  it.
- The app works without any API keys. Free keys only improve reliability and
  rate limits.

## Pull requests

- Keep changes focused and describe what user-visible behaviour changed.
- Run the backend tests and frontend build before opening a PR.
- Add or update tests for backend logic changes where practical.
- Do not change Module 1 ranking/search behaviour without explaining the
  expected effect on relevance and result counts.

## Code style

- Match the existing structure and naming in `backend/app` and `frontend/src`.
- Keep comments useful and avoid dead code.
- Do not add topic-specific hacks to ranking. Prefer general improvements that
  work across subjects.
