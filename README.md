# ARKI Recovery Engine (ARE)


ARE is an independent, local-first recovery inventory tool. Version 0.1.1 operates in READ-ONLY mode: it reads local Git metadata and working-tree state, and writes only its report files to the chosen output directory. It does not fetch, pull, checkout, merge, rebase, stage, commit, or alter scanned source repositories.

## ARE-01.1 capabilities
- Discovers repositories within user-supplied roots with a configurable depth.
- Groups linked worktrees by Git common directory so a worktree set is not counted as multiple repositories.
- Enumerates local and remote-tracking branch refs using full ref names.
- Records working-tree status and hashes content of changed regular files/symlinks (up to 50 MiB per file).
- Redacts user/password and sensitive URL query values from remote URLs.
- Explicitly marks remote freshness as `unknown_local_refs_only`; no network refresh is performed.
- Labels commit history as a 40-entry sample, not exhaustive.
- Produces JSON and Markdown inventory reports.

## Limits and safety
- Hashing is limited to changed files and 50 MiB per file; skipped items are recorded. A working-tree fingerprint is not a full repository snapshot hash.
- Git refs are local-only; remote branches may be stale.
- PRs, remote-only branches, server-side metadata, and complete history are not discovered in 0.1.1.
- A root that is itself a Git repo is treated as an entry point; linked worktrees from that repo are included even if outside that root.
- `--max-depth` limits discovery when walking directory roots; it does not limit worktrees enumerated directly from a discovered repository.
- Reports are written to the output directory. Use an output path outside the source roots to avoid report files appearing in scan coverage.

## Usage
```bash
python3 -m are scan --roots /path/to/repositories --output /path/to/reports --max-depth 5
```

## Tests
```bash
python3 -m unittest discover -s tests -v
```

No third-party dependencies required.
