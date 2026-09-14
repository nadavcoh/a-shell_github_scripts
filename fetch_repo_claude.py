#!/usr/bin/env python3
"""
fetch_repo_claude.py
--------------------
Downloads a source tarball from GitHub for a specified repository and branch,
then opens it via a-Shell's iOS share sheet to be handed off to Claude.

Supports private repos by reusing the GITHUB_TOKEN stored in
~/Documents/deploy_config.txt (the same config file used by deploy.py).

Usage (in a-Shell):
    python3 fetch_repo_claude.py <owner/repo> [-b <branch>] [-p]

Examples:
    python3 fetch_repo_claude.py youruser/photo-match-pwa -b master
    python3 fetch_repo_claude.py nadavcoh/babynames3 -b main
    python3 fetch_repo_claude.py nadavcoh/private-repo -b main -p
"""

import argparse
import urllib.request
import urllib.error
import os
import subprocess
import sys

# ── Config ────────────────────────────────────────────────────────────────────
DEST_DIR = os.path.expanduser("~/Documents")
CONFIG_PATH = os.path.expanduser("~/Documents/deploy_config.txt")
# ──────────────────────────────────────────────────────────────────────────────

def load_github_token() -> str:
    """Read GITHUB_TOKEN from the shared deploy_config.txt, if present."""
    config = {}
    if os.path.exists(CONFIG_PATH):
        for line in open(CONFIG_PATH):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()
    return config.get("GITHUB_TOKEN", "")


def download(url: str, dest: str, token: str = "") -> None:
    """Stream-download *url* to *dest* with a progress bar.

    If *token* is provided, it's sent as a Bearer token so private repo
    tarballs (and API-served archives) can be fetched.
    """
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"Downloading: {url}")

    headers = {"User-Agent": "fetch_repo_claude/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/vnd.github+json"

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            block_size = 8192
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(block_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = min(downloaded / total_size * 100, 100)
                        bar = "█" * int(pct // 5) + "░" * (20 - int(pct // 5))
                        sys.stdout.write(f"\r  [{bar}] {pct:5.1f}%")
                        sys.stdout.flush()
        print(f"\nSaved → {dest}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404) and not token:
            print(
                f"\n❌ HTTP Error: {e.code} {e.reason} - repo/branch may be private or not found.\n"
                "   If this is a private repo, retry with -p/--private "
                f"(requires GITHUB_TOKEN in {CONFIG_PATH})."
            )
        else:
            print(f"\n❌ HTTP Error: {e.code} {e.reason} - Double check the repo, branch, and token.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Download failed: {e}")
        sys.exit(1)

def open_with_claude(filepath: str) -> None:
    """Hand the file to Claude via a-Shell's native `open` command (iOS share sheet)."""
    print("\nOpening with iOS Share Sheet…")
    result = subprocess.run(["open", filepath], capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✓ File sent to share sheet — select Claude.")
    else:
        print(
            "\n⚠️  Could not open share sheet automatically.\n"
            f"   File is at: {filepath}\n"
            "   Long-press the file in the Files app and tap Share → Claude."
        )

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a GitHub repo tarball and open via iOS share sheet.")
    parser.add_argument(
        "repo", 
        help="GitHub repository in the format 'owner/repo' (e.g., nadavcoh/babynames3)"
    )
    parser.add_argument(
        "-b", "--branch", 
        default="main", 
        help="Branch name to pull (default: main)"
    )
    parser.add_argument(
        "-p", "--private",
        action="store_true",
        help=f"Authenticate using GITHUB_TOKEN from {CONFIG_PATH} (for private repos)"
    )
    
    args = parser.parse_args()

    # Safely extract just the repo name to use for the file name
    repo_name = args.repo.split("/")[-1]
    dest_filename = f"{repo_name}_{args.branch}.tar.gz"
    dest_file = os.path.join(DEST_DIR, dest_filename)

    token = ""
    if args.private:
        token = load_github_token()
        if not token:
            print(f"❌ GITHUB_TOKEN missing. Create {CONFIG_PATH} with:\n  GITHUB_TOKEN=ghp_yourtoken")
            sys.exit(1)
        # The codeload archive URL doesn't accept auth headers reliably for
        # private repos, so use the authenticated tarball API endpoint instead.
        github_url = f"https://api.github.com/repos/{args.repo}/tarball/{args.branch}"
    else:
        github_url = f"https://github.com/{args.repo}/archive/refs/heads/{args.branch}.tar.gz"

    print()
    print("=== 📦 GitHub Tarball Fetch & Open ===")
    print(f"Repo   : {args.repo}")
    print(f"Branch : {args.branch}")
    print(f"Auth   : {'private (token)' if token else 'public'}")
    print()

    download(github_url, dest_file, token=token)

    if os.path.exists(dest_file):
        size_kb = os.path.getsize(dest_file) / 1024
        print(f"Size : {size_kb:.1f} KB")
        open_with_claude(dest_file)
    print()

if __name__ == "__main__":
    main()
