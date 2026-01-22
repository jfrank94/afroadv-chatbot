"""
Admin tool to review and approve/reject platform submissions.

Usage:
    python scripts/review_submissions.py
"""

import json
from pathlib import Path
from datetime import datetime
import sys

# Paths
SUBMISSIONS_FILE = Path("data/pending_submissions.json")
PLATFORMS_FILE = Path("data/platforms.json")
APPROVED_FILE = Path("data/approved_submissions.json")
REJECTED_FILE = Path("data/rejected_submissions.json")

def load_json(file_path):
    """Load JSON file."""
    if file_path.exists():
        with open(file_path) as f:
            return json.load(f)
    return []

def save_json(file_path, data):
    """Save data to JSON file."""
    file_path.parent.mkdir(exist_ok=True)
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)

def display_submission(submission):
    """Display a submission in a readable format."""
    # Handle both old format (flat) and new format (nested)
    if 'platform' in submission:
        # New format
        platform = submission['platform']
        submitter = submission.get('submitter', {'name': 'Unknown', 'email': ''})
    else:
        # Old format - convert to platform dict
        platform = {
            'name': submission.get('name', 'Unknown'),
            'type': submission.get('type', ''),
            'category': submission.get('category', ''),
            'focus_area': submission.get('focus_area', ''),
            'description': submission.get('description', ''),
            'website': submission.get('website', ''),
            'founded': submission.get('founded', ''),
            'community_size': submission.get('community_size', ''),
            'key_programs': submission.get('key_programs', ''),
            'geographic_focus': submission.get('geographic_focus', ''),
            'tags': submission.get('tags', [])
        }
        submitter = {'name': 'Legacy submission', 'email': ''}

    print("\n" + "="*70)
    print(f"📝 SUBMISSION ID: {submission.get('id', 'unknown')}")
    print(f"🕐 Submitted: {submission.get('submitted_at', 'unknown')}")
    print("="*70)

    print(f"\n🏢 **{platform['name']}**")
    print(f"   Type: {platform['type']} | Category: {platform.get('category', 'N/A')}")
    print(f"   Website: https://{platform['website']}")
    print(f"   Focus: {platform['focus_area']}")

    print(f"\n📄 Description:")
    print(f"   {platform['description']}")

    if platform.get('founded'):
        print(f"\n📅 Founded: {platform['founded']}")
    if platform.get('community_size'):
        print(f"👥 Community Size: {platform['community_size']}")
    if platform.get('geographic_focus'):
        print(f"🌍 Geographic Focus: {platform['geographic_focus']}")
    if platform.get('key_programs'):
        print(f"🎯 Key Programs: {platform['key_programs']}")
    if platform.get('tags'):
        print(f"🏷️  Tags: {', '.join(platform['tags'])}")

    print(f"\n👤 Submitted by: {submitter['name']}")

    print("="*70)

def generate_platform_id(platform):
    """Generate a platform ID in the format: type_name_###"""
    platform_type = platform['type'].lower().replace('/', '_').replace(' ', '_')
    name_slug = platform['name'].lower()
    name_slug = ''.join(c if c.isalnum() else '_' for c in name_slug)
    name_slug = name_slug.strip('_')[:20]  # Limit length

    # Load existing platforms to find next number
    platforms = load_json(PLATFORMS_FILE)
    existing_ids = [p.get('id', '') for p in platforms]

    # Find next available number
    counter = 1
    while f"{platform_type}_{name_slug}_{counter:03d}" in existing_ids:
        counter += 1

    return f"{platform_type}_{name_slug}_{counter:03d}"

def approve_submission(submission):
    """Approve a submission and add it to platforms.json"""
    # Handle both old and new format
    if 'platform' in submission:
        platform = submission['platform']
    else:
        # Old format - use submission directly
        platform = submission

    # Generate platform ID
    platform_id = generate_platform_id(platform)

    # Load existing platforms
    platforms = load_json(PLATFORMS_FILE)

    # Create new platform entry
    new_platform = {
        "id": platform_id,
        "name": platform['name'],
        "type": platform['type'],
        "category": platform['category'],
        "focus_area": platform['focus_area'],
        "description": platform['description'],
        "website": platform['website'],
        "founded": platform.get('founded', ''),
        "community_size": platform.get('community_size', ''),
        "key_programs": platform.get('key_programs', ''),
        "geographic_focus": platform.get('geographic_focus', 'Not specified'),
        "tags": platform.get('tags', [])
    }

    # Add to platforms
    platforms.append(new_platform)

    # Save updated platforms
    save_json(PLATFORMS_FILE, platforms)

    # Mark submission as approved
    submission['status'] = 'approved'
    submission['reviewed_at'] = datetime.now().isoformat()
    submission['platform_id'] = platform_id

    # Save to approved submissions
    approved = load_json(APPROVED_FILE)
    approved.append(submission)
    save_json(APPROVED_FILE, approved)

    print(f"✅ Approved and added to database with ID: {platform_id}")
    print("⚠️  Don't forget to rebuild the index: python scripts/build_index.py")

def reject_submission(submission, reason):
    """Reject a submission."""
    submission['status'] = 'rejected'
    submission['reviewed_at'] = datetime.now().isoformat()
    submission['rejection_reason'] = reason

    # Save to rejected submissions
    rejected = load_json(REJECTED_FILE)
    rejected.append(submission)
    save_json(REJECTED_FILE, rejected)

    print(f"❌ Rejected: {reason}")

def review_submissions():
    """Main review loop."""
    # Load pending submissions
    submissions = load_json(SUBMISSIONS_FILE)
    pending = [s for s in submissions if s.get('status') == 'pending']

    if not pending:
        print("✅ No pending submissions to review!")
        return

    print(f"\n📋 {len(pending)} pending submission(s) to review\n")

    for i, submission in enumerate(pending, 1):
        display_submission(submission)

        print(f"\n[{i}/{len(pending)}] What would you like to do?")
        print("  [a] Approve and add to database")
        print("  [r] Reject with reason")
        print("  [s] Skip for now")
        print("  [q] Quit review")

        while True:
            choice = input("\nYour choice: ").strip().lower()

            if choice == 'a':
                # Approve
                approve_submission(submission)
                # Remove from pending
                submissions = [s for s in submissions if s['id'] != submission['id']]
                save_json(SUBMISSIONS_FILE, submissions)
                break

            elif choice == 'r':
                # Reject
                reason = input("Rejection reason: ").strip()
                if reason:
                    reject_submission(submission, reason)
                    # Remove from pending
                    submissions = [s for s in submissions if s['id'] != submission['id']]
                    save_json(SUBMISSIONS_FILE, submissions)
                    break
                else:
                    print("Please provide a reason for rejection.")

            elif choice == 's':
                # Skip
                print("⏭️  Skipped. Moving to next submission.")
                break

            elif choice == 'q':
                # Quit
                print("\n👋 Review session ended.")
                return

            else:
                print("Invalid choice. Please enter a, r, s, or q.")

    print("\n✅ All submissions reviewed!")
    print("\n📝 Next steps:")
    print("  1. Run: python scripts/build_index.py")
    print("  2. Push updated data/platforms.json to GitHub")

def list_submissions():
    """List all submissions with their status."""
    submissions = load_json(SUBMISSIONS_FILE)
    approved = load_json(APPROVED_FILE)
    rejected = load_json(REJECTED_FILE)

    all_submissions = submissions + approved + rejected

    if not all_submissions:
        print("No submissions found.")
        return

    print(f"\n📋 All Submissions ({len(all_submissions)} total)\n")
    print(f"{'Status':<12} {'Date':<12} {'Platform Name':<30} {'Type':<15}")
    print("-" * 70)

    for sub in all_submissions:
        status = sub.get('status', 'unknown')
        date = sub.get('submitted_at', '')[:10] if sub.get('submitted_at') else 'N/A'

        # Handle both old and new format
        if 'platform' in sub:
            name = sub['platform']['name'][:28]
            ptype = sub['platform']['type']
        else:
            name = sub.get('name', 'Unknown')[:28]
            ptype = sub.get('type', 'N/A')

        # Color code status
        status_icon = {
            'pending': '⏳',
            'approved': '✅',
            'rejected': '❌'
        }.get(status, '❓')

        print(f"{status_icon} {status:<10} {date:<12} {name:<30} {ptype:<15}")

if __name__ == "__main__":
    print("="*70)
    print("🔍 Platform Submission Review Tool")
    print("="*70)

    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        list_submissions()
    else:
        review_submissions()
