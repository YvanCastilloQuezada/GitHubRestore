import argparse
from datetime import datetime, timezone
from pathlib import Path

from .scanner import scan
from .reports import save_json, save_markdown



def main():
    parser = argparse.ArgumentParser(prog="are", description="ARKI Recovery Engine — local READ-ONLY Git inventory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan", help="Discover and inventory local Git repositories and worktrees")
    scan_parser.add_argument("--roots", nargs="+", required=True, help="One or more directories to scan")
    scan_parser.add_argument("--output", default="reports", help="Output directory for reports")
    scan_parser.add_argument("--max-depth", type=int, default=5, help="Discovery depth below each root (default: 5)")
    args = parser.parse_args()
    if args.max_depth < 0:
        parser.error("--max-depth must be >= 0")
    if args.command == "scan":
        inventory = scan(args.roots, args.max_depth)
        outdir = Path(args.output).expanduser().resolve()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        json_file = outdir / f"are_inventory_{timestamp}.json"
        markdown_file = outdir / f"are_inventory_{timestamp}.md"
        save_json(inventory, json_file)
        save_markdown(inventory, markdown_file)
        failed = sum(1 for r in inventory["repositories"] if r.get("scan_status") not in ("ok", "partial"))
        print("\n========== ARE-01.1 SCAN COMPLETE ==========")
        print("MODE: READ_ONLY")
        print(f"Repository groups: {inventory['repository_count']}")
        print(f"Working trees: {inventory.get('working_tree_count', 0)}")
        print(f"Errors: {failed}")
        print("Coverage status:", inventory["coverage_status"])
        if inventory["coverage_status"] == "empty_no_repositories_found":
            print("WARNING: No repositories discovered; this is not evidence of complete coverage.")
        print(f"Remote freshness: {inventory['remote_freshness']}")
        print(f"JSON report: {json_file}")
        print(f"Markdown report: {markdown_file}")
        print(f"Fingerprint: {inventory['inventory_fingerprint_sha256']}")
        print("==========================================")


if __name__ == "__main__":
    main()
