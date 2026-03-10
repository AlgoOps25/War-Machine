# Contributing to War Machine

## Branch Naming

| Prefix | Use for |
|--------|--------|
| `feature/` | New features or enhancements |
| `fix/` | Bug fixes |
| `optimize/` | Performance improvements |
| `analysis/` | Research / data analysis branches |
| `chore/` | Maintenance, docs, cleanup |

Examples:
- `feature/ml-confidence-booster`
- `fix/db-pool-exhaustion`
- `chore/cleanup-stale-branches`

## Commit Messages

Follow conventional commits:
```
type(scope): short description

Longer explanation if needed.
Closes #issue_number
```

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`

Examples:
```
feat(sniper): add explosive mover override bypass
fix(db): resolve pool exhaustion on Railway restart
chore: delete stale remote branches (#11)
```

## Pull Request Process

1. Branch from `main` — never commit directly to `main` or `production`
2. Keep PRs focused — one issue per PR
3. Test locally before pushing: `python app/health_check.py`
4. Reference the issue number in the PR description
5. Merge via **squash** to keep `main` history clean

## Architecture Rules

- **Do not add BOS/FVG logic** to retired detector files — use `app/signals/bos_fvg_detector.py` only
- **Do not instantiate** deprecated `signal_generator.py` — `sniper.py` owns the pipeline
- **All SQL** must use parameterized queries via `app/data/sql_safe.py`
- **All secrets** must be environment variables — never hardcode in source
- **All config constants** live in `utils/config.py` — no magic numbers in logic files

## Running Tests

```bash
python -m pytest tests/
python app/health_check.py
python scripts/system_health_check.py
```

## Deployment

- Push to `main` → Railway auto-deploys
- Use `scripts/deploy.ps1` for a controlled deploy with pre-checks
- Monitor Railway logs immediately after deploy for startup errors
