"""
One-click publish script for the e-commerce customer service system.
Orchestrates: version bump -> frontend build -> electron build -> deploy to cloud.

Usage:
    python publish.py patch                     # Bump patch: 1.0.0 -> 1.0.1
    python publish.py minor "New feature desc"  # Bump minor: 1.0.1 -> 1.1.0
    python publish.py major "Breaking changes"  # Bump major: 1.1.0 -> 2.0.0
    python publish.py deploy-only               # Deploy backend/frontend without building electron
"""
import os
import sys
import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
ELECTRON_DIR = PROJECT_ROOT / "electron-client"
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def read_version():
    """Read current version from electron-client/package.json."""
    pkg_path = ELECTRON_DIR / "package.json"
    with open(pkg_path, 'r', encoding='utf-8') as f:
        return json.load(f)['version']


def bump_version(component='patch'):
    """Bump version in electron-client/package.json."""
    pkg_path = ELECTRON_DIR / "package.json"
    with open(pkg_path, 'r', encoding='utf-8') as f:
        pkg = json.load(f)

    old_version = pkg['version']
    major, minor, patch = map(int, old_version.split('.'))

    if component == 'major':
        major += 1
        minor = 0
        patch = 0
    elif component == 'minor':
        minor += 1
        patch = 0
    else:
        patch += 1

    new_version = f"{major}.{minor}.{patch}"
    pkg['version'] = new_version

    with open(pkg_path, 'w', encoding='utf-8') as f:
        json.dump(pkg, f, indent=2, ensure_ascii=False)
        f.write('\n')

    print(f"[Version] {old_version} -> {new_version}")
    return new_version


def build_frontend():
    """Build Vue frontend for production."""
    print("\n[1/3] Building frontend...")
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=str(FRONTEND_DIR),
        shell=True,
        timeout=120,
    )
    if result.returncode != 0:
        print("[Error] Frontend build failed!")
        sys.exit(1)
    print("[OK] Frontend built successfully")


def deploy_to_server(with_electron=False, release_notes=""):
    """Run deploy.py to upload everything to cloud server."""
    step = "3/3" if with_electron else "2/2"
    print(f"\n[{step}] Deploying to cloud server...")

    cmd = [sys.executable, "deploy.py"]
    if with_electron:
        cmd.append("--with-electron")
    if release_notes:
        cmd.extend(["--notes", release_notes])

    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        timeout=900,
    )
    if result.returncode != 0:
        print("[Error] Deployment failed!")
        sys.exit(1)
    print("[OK] Deployed successfully")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python publish.py patch [release_notes]")
        print("  python publish.py minor [release_notes]")
        print("  python publish.py major [release_notes]")
        print("  python publish.py deploy-only")
        print("")
        print(f"Current version: {read_version()}")
        sys.exit(0)

    action = sys.argv[1]
    release_notes = sys.argv[2] if len(sys.argv) > 2 else ""

    # Deploy-only mode: just upload backend/frontend changes
    if action == 'deploy-only':
        print("=== Deploy Only Mode (no Electron build) ===")
        build_frontend()
        deploy_to_server(with_electron=False)
        print("\n=== Deploy complete ===")
        return

    # Full publish mode
    if action not in ('patch', 'minor', 'major'):
        print(f"Unknown action: {action}")
        print("Use: patch, minor, major, or deploy-only")
        sys.exit(1)

    current = read_version()
    print(f"=== Publishing new release ===")
    print(f"  Current version: {current}")
    print(f"  Bump type: {action}")
    if release_notes:
        print(f"  Release notes: {release_notes}")

    confirm = input("\nContinue? [y/N]: ").strip().lower()
    if confirm != 'y':
        print("Aborted.")
        sys.exit(0)

    # Step 1: Bump version
    new_version = bump_version(action)

    # Step 2: Build frontend
    build_frontend()

    # Step 3: Deploy (includes Electron build + upload + version record)
    deploy_to_server(with_electron=True, release_notes=release_notes)

    print(f"\n{'=' * 50}")
    print(f"  Release v{new_version} published successfully!")
    print(f"  Dashboard: http://120.26.199.225:8080/")
    print(f"  Update API: http://120.26.199.225:8080/api/v1/updates/check/?current_version={current}&platform=windows")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
