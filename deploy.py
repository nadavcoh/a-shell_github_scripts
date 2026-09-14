#!/usr/bin/env python3
"""
Generic deploy script for a-Shell on iOS.
Extracts a .zip or .tar.gz, commits changes, and pushes to a specified branch.
"""

import os
import sys
import subprocess
import zipfile
import tarfile
import shutil
import json
import urllib.request
import urllib.error
import argparse
from datetime import datetime

# ── Helpers ──────────────────────────────────────────────────────────────────
def die(msg):
    print(f"\n✗ {msg}", file=sys.stderr)
    sys.exit(1)

def run(*cmd, cwd=None, check=True):
    print("  $", " ".join(cmd))
    r = subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        die((r.stderr or r.stdout or f"{cmd[0]} failed").strip())
    out = (r.stdout or "").strip()
    if out:
        print(out)
    return r.returncode, out

# ── Main CLI Flow ────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="iOS Archive Git Deployment")
    parser.add_argument("repo", help="Target GitHub repo (e.g., username/my-repo)")
    parser.add_argument("branch", help="Target branch name (e.g., feature-update or main)")
    parser.add_argument("--archive", "-a", help="Path to specific archive file", default=None)
    parser.add_argument("-c", "--create-branch", action="store_true", help="Create the branch if it doesn't exist")
    parser.add_argument("--pr", action="store_true", help="Open a PR to main if a new branch is created")
    args = parser.parse_args()

    GITHUB_REPO = args.repo
    REPO_NAME = GITHUB_REPO.split("/")[-1]
    BRANCH = args.branch
    OPEN_PR = args.pr

    # ── Config & Paths ──
    CONFIG_PATH = os.path.expanduser("~/Documents/deploy_config.txt")
    config = {}
    if os.path.exists(CONFIG_PATH):
        for line in open(CONFIG_PATH):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()

    GITHUB_TOKEN = config.get("GITHUB_TOKEN", "")
    if not GITHUB_TOKEN:
        die(f"GITHUB_TOKEN missing. Create {CONFIG_PATH} with:\n  GITHUB_TOKEN=ghp_yourtoken")

    # ── Archive Detection Logic ──
    ARCHIVE = None
    if args.archive:
        target_path = os.path.expanduser(args.archive)
        if os.path.exists(target_path):
            ARCHIVE = target_path
        else:
            die(f"Specified archive not found: {target_path}")
    else:
        # Fallback to current behavior: automatically detect based on repo name
        found_archives = []
        for ext in [".zip", ".tar.gz", ".tgz", ".tar"]:
            test_path = os.path.expanduser(f"~/Documents/{REPO_NAME}{ext}")
            if os.path.exists(test_path):
                found_archives.append(test_path)
        
        if len(found_archives) > 1:
            die(f"Multiple default archives found: {', '.join(found_archives)}\n  Please specify one explicitly using the --archive flag.")
        elif len(found_archives) == 1:
            ARCHIVE = found_archives[0]

    if not ARCHIVE:
        die(f"Archive not found. Ensure '{REPO_NAME}.zip' or '{REPO_NAME}.tar.gz' exists in ~/Documents/ or provide one via --archive.")

    WORK_DIR = os.path.expanduser(f"~/Documents/{REPO_NAME}_repo")
    AUTHED_URL = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"

    print(f"\n=== 📷 Generic iOS Deployer ===")
    print(f"Repo    : {GITHUB_REPO}")
    print(f"Branch  : {BRANCH}")
    print(f"Archive : {ARCHIVE}")

    # ── Git: Clone / Fetch ──
    if os.path.isdir(os.path.join(WORK_DIR, ".git")):
        print("\n→ Fetching existing clone...")
        run("lg2", "fetch", "origin", cwd=WORK_DIR)
    else:
        print("\n→ Cloning repo...")
        os.makedirs(os.path.dirname(WORK_DIR), exist_ok=True)
        run("lg2", "clone", AUTHED_URL, WORK_DIR)

    # ── Git: Branch Logic ──
    print(f"\n→ Checking out branch '{BRANCH}'...")
    
    code, _ = run("lg2", "checkout", BRANCH, cwd=WORK_DIR, check=False)
    
    if code == 0:
        branch_exists = True
        run("lg2", "merge", f"origin/{BRANCH}", cwd=WORK_DIR, check=False)
    else:
        branch_exists = False
        if not args.create_branch:
            die(f"Branch '{BRANCH}' not found. Aborting. (Use -c or --create-branch to allow creation)")
            
        print(f"  Branch '{BRANCH}' not found. Branching off default...")
        if run("lg2", "checkout", "main", cwd=WORK_DIR, check=False)[0] != 0:
            run("lg2", "checkout", "master", cwd=WORK_DIR, check=False)
        run("lg2", "checkout", "-b", BRANCH, cwd=WORK_DIR)

    # ── Archive Extraction ──
    print("\n→ Extracting archive...")
    EXTRACT_TMP = os.path.expanduser(f"~/Documents/_{REPO_NAME}_extract")
    shutil.rmtree(EXTRACT_TMP, ignore_errors=True)
    os.makedirs(EXTRACT_TMP)

    if ARCHIVE.endswith(".zip"):
        with zipfile.ZipFile(ARCHIVE, 'r') as z:
            z.extractall(EXTRACT_TMP)
    else:
        with tarfile.open(ARCHIVE) as t:
            # Handle Python 3.12+ tarfile extraction warning
            if hasattr(tarfile, 'data_filter'):
                t.extractall(EXTRACT_TMP, filter='data')
            else:
                t.extractall(EXTRACT_TMP)

    # If the archive root contains exactly one entry, it's a directory, and
    # that directory's name matches the repo name, treat its contents as the
    # actual source root (handles archives that wrap everything in a single
    # top-level folder, e.g. "myrepo/...").
    root_entries = os.listdir(EXTRACT_TMP)
    if len(root_entries) == 1:
        sole_entry = root_entries[0]
        sole_path = os.path.join(EXTRACT_TMP, sole_entry)
        if os.path.isdir(sole_path) and sole_entry == REPO_NAME:
            print(f"  Detected single wrapping folder '{sole_entry}', flattening...")
            SOURCE_ROOT = sole_path
        else:
            SOURCE_ROOT = EXTRACT_TMP
    else:
        SOURCE_ROOT = EXTRACT_TMP

    SKIP = {"venv", "__pycache__", ".git", "thumbnails_cache"}
    for item in os.listdir(SOURCE_ROOT):
        if item in SKIP or item.endswith(".db"):
            continue
        src = os.path.join(SOURCE_ROOT, item)
        dst = os.path.join(WORK_DIR, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

    shutil.rmtree(EXTRACT_TMP, ignore_errors=True)

    # ── Git: Commit & Push ──
    print("\n→ Committing...")
    run("lg2", "add", ".", cwd=WORK_DIR)
    code, status = run("lg2", "status", "--short", cwd=WORK_DIR, check=False)
    
    if not status:
        die("No changes to commit. Archive is identical to the current branch state.")

    PR_TITLE = f"Update from iOS: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    run("lg2", "commit", "-m", PR_TITLE, cwd=WORK_DIR)

    print(f"\n→ Pushing '{BRANCH}'...")
    run("lg2", "push", cwd=WORK_DIR)

    # Get local pushed commit hash by reading the branch ref
    commit_hash = "unknown"
    ref_path = os.path.join(WORK_DIR, ".git", "refs", "heads", BRANCH)
    if os.path.exists(ref_path):
        with open(ref_path, "r") as f:
            commit_hash = f.read().strip()
    
    print(f"\n✓ Remote commit hash: {commit_hash}")

    # ── GitHub PR Flow ──
    if OPEN_PR and not branch_exists and BRANCH not in ["main", "master"]:
        print("\n→ Creating GitHub PR to 'main'...")
        payload = json.dumps({
            "title": PR_TITLE,
            "head": BRANCH,
            "base": "main",
            "body": "Automated update pushed directly from iOS via a-Shell 📱"
        }).encode()

        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/pulls",
            data=payload,
            headers={
                "Authorization":        f"Bearer {GITHUB_TOKEN}",
                "Accept":               "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type":         "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                pr = json.loads(resp.read())
            pr_url = pr["html_url"]
            print(f"✓ PR created: {pr_url}")
            try:
                run("open", pr_url, check=False)
            except Exception:
                pass
        except urllib.error.HTTPError as e:
            body = json.loads(e.read())
            die(f"GitHub API Error: {body.get('message', str(e))}")
    elif OPEN_PR and (branch_exists or BRANCH in ["main", "master"]):
        print("\n✓ Changes pushed. PR skipped (either updating existing branch or pushed directly to main).")
    else:
        print("\n✓ Code successfully pushed.")

if __name__ == "__main__":
    main()
