from pathlib import Path
import os
import hashlib
import json
from datetime import datetime, timezone


from .git_utils import (
    root_of, is_repo, common_dir, list_branches, repository_status,
    list_remotes, list_worktrees, list_stashes, recent_commits,
    detect_default_branch, branch_merge_analysis, git_safe, git,
)


SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", "dist", "build"}
MAX_CHANGED_FILE_BYTES = 50 * 1024 * 1024



def fingerprint(obj):
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()



def discover_working_trees(roots, max_depth=5):
    """Discover working trees, then group linked worktrees by Git common directory."""
    found = {}
    for root in roots:
        root = Path(root).expanduser().resolve()
        if not root.exists():
            print(f"[WARN] Root does not exist: {root}")
            continue
        if is_repo(root):
            repo_root = root_of(root)
            if repo_root:
                cdir = common_dir(repo_root)
                key = str(cdir or repo_root)
                found.setdefault(key, {"common_dir": str(cdir) if cdir else None, "paths": set()})["paths"].add(repo_root)
                # Include every linked worktree recorded by Git, even if outside the scan root.
                for wt in list_worktrees(repo_root):
                    p = Path(wt.get("path", "")).expanduser()
                    if p.exists():
                        found[key]["paths"].add(p.resolve())
            continue
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            try:
                depth = len(current_path.relative_to(root).parts)
            except ValueError:
                depth = max_depth
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and depth < max_depth]
            if ".git" in dirs or ".git" in files:
                repo_root = root_of(current_path)
                if repo_root:
                    cdir = common_dir(repo_root)
                    key = str(cdir or repo_root)
                    found.setdefault(key, {"common_dir": str(cdir) if cdir else None, "paths": set()})["paths"].add(repo_root)
                    for wt in list_worktrees(repo_root):
                        p = Path(wt.get("path", "")).expanduser()
                        if p.exists():
                            found[key]["paths"].add(p.resolve())
                dirs[:] = []
    return [{"common_dir": value["common_dir"], "paths": sorted(value["paths"])} for _, value in sorted(found.items())]


def hash_changed_files(repo, changes):
    records, skipped = [], []
    for change in changes:
        path_text = change.get("destination_path") or change["path"]
        p = Path(repo) / path_text
        try:
            if not p.exists() and not p.is_symlink():
                records.append({"path": path_text, "state": "deleted_or_missing"})
                continue
            st = p.lstat()
            if p.is_symlink():
                target = os.readlink(p)
                digest = hashlib.sha256(target.encode("utf-8", "surrogateescape")).hexdigest()
                records.append({"path": path_text, "type": "symlink", "sha256": digest, "size_bytes": len(target)})
            elif p.is_file():
                if st.st_size > MAX_CHANGED_FILE_BYTES:
                    skipped.append({"path": path_text, "reason": "size_limit", "size_bytes": st.st_size})
                    continue
                h = hashlib.sha256()
                with p.open("rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(chunk)
                records.append({"path": path_text, "type": "file", "sha256": h.hexdigest(), "size_bytes": st.st_size})
            else:
                records.append({"path": path_text, "type": "non_regular", "state": "not_hashed"})
        except Exception as exc:
            skipped.append({"path": path_text, "reason": type(exc).__name__})
    return records, skipped


def scan_worktree(repo):
    status = repository_status(repo)
    file_hashes, skipped = hash_changed_files(repo, status["changes"])
    return {
        "path": str(repo),
        "name": repo.name,
        "status": status,
        "changed_file_content_hashes": file_hashes,
        "hash_coverage": {"changed_files_total": len(status["changes"]), "hashed": len(file_hashes),
                          "skipped": len(skipped), "skipped_details": skipped,
                          "complete": len(skipped) == 0 and len(file_hashes) >= len(status["changes"])},
        "worktree_fingerprint_sha256": fingerprint({"status": status, "hashes": file_hashes, "skipped": skipped}),
    }


def scan_group(group):
    paths = [Path(p) for p in group["paths"]]
    representative = paths[0]
    default_branch = detect_default_branch(representative)
    worktree_records = []
    errors = []
    for path in paths:
        try:
            worktree_records.append(scan_worktree(path))
        except Exception as exc:
            errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
    branches = list_branches(representative)
    commits = recent_commits(representative, 40)
    record = {
        "path": str(representative),
        "name": representative.name,
        "common_git_dir": group["common_dir"],
        "scan_status": "ok" if not errors else "partial",
        "default_branch": default_branch,
        "branches": branches,
        "remotes": list_remotes(representative),
        "worktrees": list_worktrees(representative),
        "working_trees": worktree_records,
        "working_tree_errors": errors,
        "stashes": list_stashes(representative),
        "merged_branch_analysis": branch_merge_analysis(representative, default_branch) if default_branch else {"status": "no_default_branch"},
        "recent_commits_sample": commits,
        "recent_commits_sample_limit": 40,
        "recent_commits_is_exhaustive": False,
        "history_sampling_note": "Only the latest 40 commits reachable from local refs are sampled; this is not a complete history inventory.",
    }
    record["repository_fingerprint_sha256"] = fingerprint(record)
    return record


def scan(roots, max_depth=5):
    groups = discover_working_trees(roots, max_depth)
    records = []
    for group in groups:
        print(f"[SCAN] common-dir={group['common_dir']} paths={len(group['paths'])}")
        try:
            records.append(scan_group(group))
        except Exception as exc:
            records.append({"path": group["paths"][0] if group["paths"] else "unknown", "scan_status": "error",
                           "error": f"{type(exc).__name__}: {exc}", "common_git_dir": group["common_dir"],
                           "working_tree_paths": group["paths"]})
    inventory = {
        "schema": "are.source_inventory.v1.1",
        "engine": "ARKI Recovery Engine",
        "engine_version": "0.1.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY",
        "remote_freshness": "unknown_local_refs_only",
        "network_access": False,
        "warning": "This inventory reflects local Git refs and local working trees only. No remote refresh was performed.",
        "roots": [str(Path(p).expanduser().resolve()) for p in roots],
        "max_depth": max_depth,
        "repository_count": len(records),
        "working_tree_count": sum(len(r.get("working_trees", [])) for r in records),
        "coverage_status": "complete_local_scan" if records else "empty_no_repositories_found",
        "repositories": records,
    }
    stable = dict(inventory)
    stable.pop("generated_at_utc", None)
    inventory["inventory_fingerprint_sha256"] = fingerprint(stable)
    return inventory
