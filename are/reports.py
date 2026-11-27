import json
from pathlib import Path


def save_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _md_cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def save_markdown(data, path):
    lines = [
        "# ARE-01.1 — Source Inventory", "",
        f"- Scan time (UTC): `{data['generated_at_utc']}`",
        f"- Mode: **{data['mode']}**",
        f"- Engine version: **{data['engine_version']}**",
        f"- Repository groups: **{data['repository_count']}**",
        f"- Working trees: **{data.get('working_tree_count', 0)}**",
        f"- Remote freshness: **{data.get('remote_freshness', 'unknown')}**",
        f"- Inventory SHA-256: `{data['inventory_fingerprint_sha256']}`", "",
        f"> **Limitation:** {_md_cell(data.get('warning', ''))}", "",
        "## Summary", "",
        "| Repository group | Default branch | Branch refs | Worktrees | Stashes | Status |",
        "|---|---|---:|---:|---:|---|",
    ]
    for r in data["repositories"]:
        status = r.get("scan_status", "error")
        lines.append(f"| {_md_cell(r.get('name', r.get('path', '?')))} | {_md_cell(r.get('default_branch') or 'unknown')} | {len(r.get('branches', []))} | {len(r.get('working_trees', []))} | {len(r.get('stashes', []))} | {status} |")
    lines.extend(["", "## Repository details", ""])
    for r in data["repositories"]:
        lines.extend([f"### {_md_cell(r.get('name', 'unknown'))}", "", f"- Representative path: `{r.get('path', '')}`", f"- Common Git directory: `{r.get('common_git_dir', '')}`", f"- Scan status: **{r.get('scan_status', 'unknown')}**", f"- Repository fingerprint: `{r.get('repository_fingerprint_sha256', 'unavailable')}`", ""])
        if r.get("error"):
            lines.append(f"- Error: `{_md_cell(r['error'])}`")
            continue
        lines.extend(["#### Branch refs", "", "| Ref | Kind | Commit date | SHA | Subject |", "|---|---|---|---|---|"])
        for b in r.get("branches", []):
            lines.append(f"| `{_md_cell(b.get('ref'))}` | {_md_cell(b.get('kind'))} | {_md_cell(b.get('commit_date'))} | `{b.get('sha', '')[:12]}` | {_md_cell(b.get('subject'))} |")
        lines.extend(["", "#### Working trees", "", "| Path | Branch | Clean | Changes | Fingerprint coverage | Fingerprint |", "|---|---|---|---:|---|---|"])
        for wt in r.get("working_trees", []):
            status = wt.get("status", {})
            cov = wt.get("hash_coverage", {})
            lines.append(f"| `{_md_cell(wt.get('path'))}` | {_md_cell(status.get('branch'))} | {status.get('clean')} | {len(status.get('changes', []))} | {cov.get('hashed', 0)}/{cov.get('changed_files_total', 0)} ({'complete' if cov.get('complete') else 'partial'}) | `{wt.get('worktree_fingerprint_sha256', '')[:12]}` |")
            if status.get("changes"):
                lines.append("  - Changes:")
                for c in status["changes"]:
                    lines.append(f"    - `{c.get('index_status')}{c.get('worktree_status')}` `{_md_cell(c.get('path'))}`")
            if cov.get("skipped_details"):
                lines.append("  - Hash skips:")
                for item in cov["skipped_details"]:
                    lines.append(f"    - `{_md_cell(item.get('path'))}` — {_md_cell(item.get('reason'))}")
        lines.extend(["", "#### Remotes", ""])
        if not r.get("remotes"):
            lines.append("- No remotes detected.")
        for remote in r.get("remotes", []):
            lines.append(f"- `{_md_cell(remote.get('name'))}` — `fetch: {_md_cell(remote.get('fetch_url'))}`; `push: {_md_cell(remote.get('push_url'))}` ({', '.join(remote.get('directions', []))})")
        lines.extend(["", "#### Stashes", ""])
        if not r.get("stashes"):
            lines.append("- None.")
        for stash in r.get("stashes", []):
            lines.append(f"- `{stash.get('selector')}` `{stash.get('sha', '')[:12]}` {_md_cell(stash.get('date'))} — {_md_cell(stash.get('subject'))}")
        lines.extend(["", "#### Commit sample", "", f"- Sample size: {r.get('recent_commits_sample_limit', 40)}", "- Exhaustive: **No**", ""])
        for c in r.get("recent_commits_sample", []):
            lines.append(f"- `{c.get('sha', '')[:12]}` · {_md_cell(c.get('date'))} · {_md_cell(c.get('author'))} · {_md_cell(c.get('subject'))}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
