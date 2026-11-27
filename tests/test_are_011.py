import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from are.git_utils import classify_ref, redact_remote_url, parse_porcelain_v1_z
from are.scanner import discover_working_trees, scan, scan_worktree


def run_git(path, *args):
    p = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr)
    return p.stdout.strip()


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        run_git(self.repo, "init", "-b", "main")
        run_git(self.repo, "config", "user.name", "ARE Test")
        run_git(self.repo, "config", "user.email", "are@example.test")
        (self.repo / "tracked.txt").write_text("baseline\n")
        run_git(self.repo, "add", "tracked.txt")
        run_git(self.repo, "commit", "-m", "initial commit")

    def tearDown(self):
        self.temp.cleanup()



class TestARE011(GitFixture):
    def test_branch_ref_classification(self):
        self.assertEqual(classify_ref("refs/heads/main"), ("local", "main"))
        self.assertEqual(classify_ref("refs/remotes/origin/topic"), ("remote", "origin/topic"))
        self.assertEqual(classify_ref("refs/remotes/origin/HEAD"), ("symbolic_remote_head", "origin/HEAD"))
        self.assertEqual(classify_ref("refs/tags/v1"), ("tag", "v1"))

    def test_branch_listing_uses_full_refs(self):
        run_git(self.repo, "update-ref", "refs/remotes/origin/remote-topic", "HEAD")
        result = scan([self.repo])
        branches = result["repositories"][0]["branches"]
        self.assertTrue(any(b["kind"] == "local" and b["ref"] == "main" for b in branches))
        self.assertTrue(any(b["kind"] == "remote" and b["ref"] == "origin/remote-topic" for b in branches))
        self.assertFalse(any(b["kind"] == "unknown" for b in branches))

    def test_dirty_file_content_fingerprint_changes(self):
        initial = scan_worktree(self.repo)["worktree_fingerprint_sha256"]
        (self.repo / "tracked.txt").write_text("changed content\n")
        updated = scan_worktree(self.repo)["worktree_fingerprint_sha256"]
        self.assertNotEqual(initial, updated)

    def test_untracked_file_is_detected_and_hashed(self):
        (self.repo / "new file.txt").write_text("untracked evidence\n")
        result = scan_worktree(self.repo)
        self.assertEqual(result["hash_coverage"]["hashed"], 1)
        self.assertTrue(result["hash_coverage"]["complete"])
        self.assertIn("new file.txt", [x["path"] for x in result["changed_file_content_hashes"]])

    def test_linked_worktree_grouped(self):
        wt = self.base / "linked-worktree"
        run_git(self.repo, "worktree", "add", "-b", "feature/test", str(wt))
        groups = discover_working_trees([self.base], max_depth=4)
        self.assertEqual(len(groups), 1)
        paths = {Path(p) for p in groups[0]["paths"]}
        self.assertIn(self.repo.resolve(), paths)
        self.assertIn(wt.resolve(), paths)

    def test_scan_reports_local_only_and_group_counts(self):
        wt = self.base / "wt2"
        run_git(self.repo, "worktree", "add", "-b", "feature/wt2", str(wt))
        result = scan([self.base], max_depth=4)
        self.assertEqual(result["repository_count"], 1)
        self.assertEqual(result["working_tree_count"], 2)
        self.assertEqual(result["remote_freshness"], "unknown_local_refs_only")
        self.assertFalse(result["network_access"])
        self.assertEqual(result["engine_version"], "0.1.1")

    def test_remote_credentials_redacted(self):
        safe = redact_remote_url("https://alice:secret@github.com/user/repo.git?access_token=abc&x=1")
        self.assertNotIn("alice", safe)
        self.assertNotIn("secret", safe)
        self.assertNotIn("abc", safe)
        self.assertIn("[REDACTED]", safe)
        self.assertIn("x=1", safe)

    def test_porcelain_parser_paths_with_spaces_and_newlines(self):
        raw = b" M path with spaces.txt\0?? untracked\nname.txt\0"
        parsed = parse_porcelain_v1_z(raw)
        self.assertEqual(parsed[0]["path"], "path with spaces.txt")
        self.assertEqual(parsed[1]["path"], "untracked\nname.txt")

    def test_commit_subject_with_pipe_survives(self):
        run_git(self.repo, "commit", "--allow-empty", "-m", "subject | has pipe")
        result = scan([self.repo])
        subjects = [b["subject"] for b in result["repositories"][0]["branches"]]
        self.assertTrue(any("subject | has pipe" in subject for subject in subjects))


if __name__ == "__main__":
    unittest.main()
