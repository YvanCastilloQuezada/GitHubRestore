from __future__ import annotations

from pathlib import Path
import hashlib
import os
import subprocess
import urllib.parse


def git(repo: Path, *args: str, timeout: int = 30, raw: bool = False):
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not raw,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace") if raw else proc.stderr
        raise RuntimeError(err.strip() or "Git command failed")
    return proc.stdout if raw else proc.stdout.rstrip("\n")


def git_safe(repo: Path, *args: str):
    try:
        return git(repo, *args)
    except Exception:
        return None


def root_of(repo: Path):
    result = git_safe(repo, "rev-parse", "--show-toplevel")
    return Path(result).resolve() if result else None



def common_dir(repo: Path):
    result = git_safe(repo, "rev-parse", "--git-common-dir")
    if not result:
        return None
    p = Path(result)
    if not p.is_absolute():
        p = repo / p
    return p.resolve()


def is_repo(path: Path):
    return (path / ".git").exists() or git_safe(path, "rev-parse", "--show-toplevel") is not None


def classify_ref(ref: str):
    if ref.startswith("refs/heads/"):
        return "local", ref[len("refs/heads/"):]
    if ref.startswith("refs/remotes/"):
        tail = ref[len("refs/remotes/"):]
        if tail.endswith("/HEAD"):
            return "symbolic_remote_head", tail
        return "remote", tail
    if ref.startswith("refs/tags/"):
        return "tag", ref[len("refs/tags/"):]
    return "other", ref


def list_branches(repo: Path):
    fmt = "%(refname)%00%(objectname)%00%(committerdate:iso8601-strict)%00%(subject)%00"
    output = git(repo, "for-each-ref", "--format=" + fmt, "refs/heads", "refs/remotes", raw=True)
    text = output.decode("utf-8", "replace")
    fields = text.split("\x00")
    branches = []
    for i in range(0, len(fields) - 3, 4):
        ref, sha, date, subject = fields[i:i+4]
        ref, sha, date = ref.strip(), sha.strip(), date.strip()
        subject = subject.strip("\r\n")
        if not ref:
            continue
        kind, short_ref = classify_ref(ref)
        if kind == "symbolic_remote_head":
            continue
        branches.append({"ref": short_ref, "full_ref": ref, "kind": kind, "sha": sha,
                        "commit_date": date, "subject": subject})
    return branches


def parse_porcelain_v1_z(data: bytes):
    """Parse git status --porcelain=v1 -z safely, preserving paths with spaces/newlines."""
    entries = data.decode("utf-8", "surrogateescape").split("\x00")
    changes = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        if not entry:
            i += 1
            continue
        if len(entry) < 3:
            i += 1
            continue
        x, y = entry[0], entry[1]
        path = entry[3:]
        changes.append({"index_status": x, "worktree_status": y, "path": path})
        # Rename/copy records have an additional path field in -z mode.
        if x == "R" or y == "R" or x == "C" or y == "C":
            i += 1
            if i < len(entries) and entries[i]:
                changes[-1]["destination_path"] = entries[i]
        i += 1
    return changes


def repository_status(repo: Path):
    branch = git_safe(repo, "branch", "--show-current") or "(detached)"
    raw = git(repo, "status", "--porcelain=v1", "-z", raw=True)
    changes = parse_porcelain_v1_z(raw)
    return {"branch": branch, "clean": len(changes) == 0, "changes": changes}


def redact_remote_url(url: str):
    """Remove user/password and sensitive query keys from URLs, without leaking credentials."""
    try:
        parts = urllib.parse.urlsplit(url)
        if not parts.scheme or not parts.netloc:
            # SCP-style Git URL: user@host:path
            if "@" in url and ":" in url:
                userhost, path = url.split(":", 1)
                host = userhost.split("@", 1)[-1]
                return f"{host}:{path}"
            return url
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        sensitive = {"token", "access_token", "auth", "authorization", "password", "key", "secret"}
        safe_query = [(k, "[REDACTED]" if k.lower() in sensitive else v) for k, v in query]
        return urllib.parse.urlunsplit((parts.scheme, host, parts.path, urllib.parse.urlencode(safe_query, safe="[]"), parts.fragment))
    except Exception:
        return "[URL REDACTED: PARSE ERROR]"


def list_remotes(repo: Path):
    output = git_safe(repo, "remote") or ""
    remotes = []
    for name in output.splitlines():
        url = git_safe(repo, "remote", "get-url", name) or ""
        push_url = git_safe(repo, "remote", "get-url", "--push", name) or url
        remotes.append({"name": name, "fetch_url": redact_remote_url(url), "push_url": redact_remote_url(push_url), "directions": ["fetch", "push"]})
    return remotes


def list_worktrees(repo: Path):
    output = git(repo, "worktree", "list", "--porcelain")
    entries, current = [], {}
    for line in output.splitlines():
        if line.startswith("worktree "):
            if current:
                entries.append(current)
            current = {"path": line[len("worktree "):]} 
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):].replace("refs/heads/", "", 1)
        elif line.strip() == "detached":
            current["detached"] = True
        elif line.strip() == "prunable":
            current["prunable"] = True
    if current:
        entries.append(current)
    return entries


def list_stashes(repo: Path):
    output = git_safe(repo, "stash", "list", "--format=%gd|%H|%ci|%s") or ""
    entries = []
    for line in output.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            entries.append({"selector": parts[0], "sha": parts[1], "date": parts[2], "subject": parts[3]})
    return entries


def recent_commits(repo: Path, count=40):
    fmt = "%H%x00%cI%x00%an%x00%s%x00"
    output = git(repo, "log", "--all", f"-n{count}", "--format=" + fmt, raw=True).decode("utf-8", "replace")
    fields = output.split("\x00")
    entries = []
    for i in range(0, len(fields)-3, 4):
        sha, date, author, subject = fields[i:i+4]
        sha, date, author = sha.strip(), date.strip(), author.strip()
        subject = subject.strip("\r\n")
        if sha:
            entries.append({"sha": sha, "date": date, "author": author, "subject": subject})
    return entries


def detect_default_branch(repo: Path):
    local = set((git_safe(repo, "branch", "--format=%(refname:short)") or "").splitlines())
    for candidate in ("main", "master"):
        if candidate in local:
            return candidate
    symbolic = git_safe(repo, "symbolic-ref", "refs/remotes/origin/HEAD")
    if symbolic:
        return symbolic.rsplit("/", 1)[-1]
    return None


def branch_merge_analysis(repo: Path, base: str):
    merged_output = git_safe(repo, "branch", "--merged", base, "--format=%(refname:short)")
    all_output = git_safe(repo, "branch", "--format=%(refname:short)")
    if merged_output is None or all_output is None:
        return {"base": base, "status": "unavailable"}
    merged, all_local = set(merged_output.splitlines()), set(all_output.splitlines())
    return {"base": base, "merged_local": sorted(merged), "not_merged_local": sorted(all_local-merged)}
