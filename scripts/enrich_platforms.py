"""Platform enrichment script.

Searches the web for each platform and updates fields in platforms.json:
    - community_size  (current member count)
    - states          (US states with active chapters)
    - still_active    (flags defunct platforms for review)

Designed to be safe and resumable:
    - Progress is saved after every platform so crashes don't lose work
    - Re-running the script skips already-processed platforms
    - All changes are written to platforms.json with an automatic backup
    - A human-readable change log is printed at the end

Usage:
    python scripts/enrich_platforms.py              # Full run
    python scripts/enrich_platforms.py --dry-run    # Preview without writing
    python scripts/enrich_platforms.py --platform outdoor_afro_001
    python scripts/enrich_platforms.py --force      # Re-process completed platforms
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import logging
import argparse
import time
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

import config
from src.agents.tools.web_searcher import search_platform_info
from src.agents.tools.llm_extractor import extract_updates, PlatformUpdate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── File paths ──────────────────────────────────────────────────────────────
PLATFORMS_FILE = config.PLATFORMS_JSON
PROGRESS_FILE = config.DATA_DIR / "enrichment_progress.json"
BACKUP_FILE = config.DATA_DIR / "platforms.json.enrich_backup"

# Delay between platforms to avoid Tavily rate-limit bursts
REQUEST_DELAY_SECONDS = 1.0


# ── Progress helpers ─────────────────────────────────────────────────────────

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"completed": [], "failed": {}, "needs_review": [], "changes": []}


def save_progress(progress: dict) -> None:
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


# ── Merge helpers ─────────────────────────────────────────────────────────────

def merge_update(platform: dict, update: PlatformUpdate) -> tuple[dict, list[str]]:
    """Apply a PlatformUpdate onto a platform dict, returning the updated dict and a list of changes made.

    Merging rules:
    - community_size: replace only if confidence is high or medium
    - states: union of existing + new (never removes existing confirmed states)
    - still_active=False: flag for review, do NOT auto-remove
    """
    changes = []
    updated = platform.copy()

    if update.community_size and update.confidence in ("high", "medium"):
        old = platform.get("community_size", "")
        if update.community_size != old:
            updated["community_size"] = update.community_size
            changes.append(f"community_size: '{old}' → '{update.community_size}'")

    if update.states:
        existing = set(platform.get("states", []))
        new_states = set(update.states) - existing
        if new_states:
            merged = sorted(existing | new_states)
            updated["states"] = merged
            changes.append(f"states: added {sorted(new_states)}")

    if not update.still_active:
        changes.append("FLAGGED: may be inactive — manual review required")

    return updated, changes


# ── Core enrichment loop ──────────────────────────────────────────────────────

def enrich_platform(platform: dict) -> tuple[PlatformUpdate, list[str]]:
    """Run web search + LLM extraction for a single platform.

    Returns:
        (update, changes) where changes is a list of human-readable diff strings.
    """
    name = platform["name"]
    platform_type = platform.get("type", "")

    results = search_platform_info(name, platform_type)
    update = extract_updates(name, results)
    _, changes = merge_update(platform, update)

    return update, changes


def run(
    platforms_file: Path,
    dry_run: bool = False,
    target_id: Optional[str] = None,
    force: bool = False,
) -> None:
    """Main enrichment loop.

    Args:
        platforms_file: Path to platforms.json
        dry_run: If True, print changes without writing to disk
        target_id: Process only this platform ID (for testing)
        force: Re-process platforms already marked as completed
    """
    platforms: list[dict] = json.loads(platforms_file.read_text())
    progress = load_progress()

    # Filter to target platform if specified
    if target_id:
        platforms = [p for p in platforms if p.get("id") == target_id]
        if not platforms:
            logger.error(f"Platform ID not found: {target_id}")
            sys.exit(1)

    total = len(platforms)
    logger.info(f"Loaded {total} platforms from {platforms_file}")
    if not force:
        already_done = len([p for p in platforms if p["id"] in progress["completed"]])
        logger.info(f"{already_done} already completed — will skip (use --force to re-run)")

    updated_platforms = {p["id"]: p for p in json.loads(platforms_file.read_text())}

    for i, platform in enumerate(platforms, 1):
        pid = platform["id"]
        name = platform["name"]

        if not force and pid in progress["completed"]:
            logger.info(f"[{i}/{total}] Skipping {name} (already done)")
            continue

        logger.info(f"[{i}/{total}] Enriching: {name}")

        try:
            update, changes = enrich_platform(platform)

            if changes:
                merged, _ = merge_update(platform, update)
                updated_platforms[pid] = merged
                for change in changes:
                    logger.info(f"  ✓ {change}")
                progress["changes"].append({
                    "id": pid,
                    "name": name,
                    "changes": changes,
                    "confidence": update.confidence,
                })
            else:
                logger.info(f"  — No updates found (confidence: {update.confidence})")

            if update.needs_review and pid not in progress["needs_review"]:
                progress["needs_review"].append(pid)
                if update.notes:
                    logger.info(f"  ⚠ Flagged for review: {update.notes}")

            progress["completed"].append(pid)

        except Exception as e:
            logger.error(f"  ✗ Failed: {e}")
            progress["failed"][pid] = str(e)

        finally:
            if not dry_run:
                save_progress(progress)
            time.sleep(REQUEST_DELAY_SECONDS)

    # ── Write results ────────────────────────────────────────────────────────
    _print_summary(progress, total)

    if dry_run:
        logger.info("Dry run — no files written.")
        return

    if progress["changes"]:
        # Backup original before writing
        BACKUP_FILE.write_text(platforms_file.read_text())
        logger.info(f"Backup saved to {BACKUP_FILE}")

        final_platforms = list(updated_platforms.values())
        platforms_file.write_text(json.dumps(final_platforms, indent=2, ensure_ascii=False))
        logger.info(f"Updated platforms.json ({len(progress['changes'])} platform(s) changed)")
        logger.info("Run 'bash scripts/update_all.sh' to rebuild the index.")
    else:
        logger.info("No changes to write.")


def _print_summary(progress: dict, total: int) -> None:
    print("\n" + "=" * 60)
    print("ENRICHMENT SUMMARY")
    print("=" * 60)
    print(f"Total:         {total}")
    print(f"Completed:     {len(progress['completed'])}")
    print(f"Failed:        {len(progress['failed'])}")
    print(f"Changed:       {len(progress['changes'])}")
    print(f"Needs review:  {len(progress['needs_review'])}")

    if progress["changes"]:
        print("\n── Changes ──────────────────────────────────────────────")
        for entry in progress["changes"]:
            print(f"\n{entry['name']} (confidence: {entry['confidence']})")
            for change in entry["changes"]:
                print(f"  • {change}")

    if progress["failed"]:
        print("\n── Failed ───────────────────────────────────────────────")
        for pid, error in progress["failed"].items():
            print(f"  {pid}: {error}")

    if progress["needs_review"]:
        print("\n── Needs Manual Review ──────────────────────────────────")
        for pid in progress["needs_review"]:
            print(f"  {pid}")

    print("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enrich platforms.json with up-to-date info from web search."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to disk.",
    )
    parser.add_argument(
        "--platform",
        type=str,
        metavar="ID",
        help="Process a single platform by ID (e.g. outdoor_afro_001).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process platforms already marked as completed.",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=str(PLATFORMS_FILE),
        help=f"Path to platforms.json (default: {PLATFORMS_FILE})",
    )
    args = parser.parse_args()

    if not Path(args.file).exists():
        logger.error(f"File not found: {args.file}")
        sys.exit(1)

    try:
        run(
            platforms_file=Path(args.file),
            dry_run=args.dry_run,
            target_id=args.platform,
            force=args.force,
        )
    except KeyboardInterrupt:
        print("\n\nInterrupted — progress saved. Re-run to continue.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
