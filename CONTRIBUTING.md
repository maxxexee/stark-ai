# Contributing to Stark

Product context and the app map are in the [README](README.md).

## Setup

```sh
bun install
bun dev           # website :5173, dashboard :5174, API :8000
```

Requirements: Node 22+ (`.nvmrc` says 24), Bun 1.3+ (pinned via `packageManager`),
Python 3.9+. Rust only if you touch [`apps/contracts`](apps/contracts/README.md).

Configuration lives in [Infisical](https://infisical.com), project `stark`, one folder
per app (`/backend`, `/dashboard`, `/website`) in each environment. Install the CLI
(`brew install infisical/get-cli/infisical`) and run `infisical login` once.
`.infisical.yaml` already links the repo to the project, and every `dev` script runs
through `infisical secrets-manager run`. To see or change a value, run
`infisical secrets-manager secrets --env dev --path /backend`.
[`apps/backend/.env.example`](apps/backend/.env.example) documents each key. Never commit a `.env`.

## Making a change

1. Branch from `main`: `feat/bill-reminders`, `fix/dashboard-cap-rounding`.
2. Read the README of the app you are changing and follow its rules.
3. Keep a change to one concern. A UI change and an API change are two pull requests
   unless one cannot land without the other.
4. Before pushing, run:

   ```sh
   bun check         # typecheck + lint + backend unit tests
   bun run build     # website and dashboard build
   bun smoke         # if you touched the backend: start it first with `bun dev:backend`
   ```

   If you changed the contract, also run `bun --filter @stark/contracts run contract:test`.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org):

```
type(scope): imperative summary in lowercase

Why the change was needed, wrapped at ~72-100 characters.
```

- `type`: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`
- `scope`: the app or area, e.g. `website`, `dashboard`, `ui`, `api`, `backend`, `contracts`, `docs`

Example: `fix(backend): reuse request_id when retrying a pending vend`.

## Pull requests

- Say what changed and why, and how you verified it. Screenshots for any visible UI change.
- Link the issue or milestone (M0–M7 in [`docs/HANDOFF.md`](docs/HANDOFF.md)) it moves forward.
- A PR is ready when `bun check && bun run build` passes.

## Rules that apply everywhere

- **The API contract in [`docs/API.md`](docs/API.md) is frozen.** Additive changes only.
  A rename or type change means `/v2`. Update `API.md` in the same PR as the code.
- **Money is integer naira.** No floats, no kobo.
- **Branch on error `code`, never on `message`.**
- **No crypto jargon in user-facing copy** ("vault", "USDC", addresses), and **no sliders**.
- **Never commit secrets.** Keys go in env vars.
- **`apps/backend/policy.py` mirrors `apps/contracts/vault/src/policy.rs`.** Change both
  together; a test fails if they drift.
- **Payments stay dry-run by default.** Anything that vends, signs or broadcasts for real
  must be switched on by an env var, and must refuse to start when misconfigured.
