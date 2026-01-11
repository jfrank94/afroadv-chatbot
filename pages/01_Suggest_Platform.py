"""
Platform Submission Form

Allows users to suggest new platforms for inclusion in the database.
Submissions are stored in data/pending_submissions.json for admin review.
"""

import streamlit as st
import json
from pathlib import Path
from datetime import datetime
import uuid

# Page config
st.set_page_config(
    page_title="Suggest a Platform",
    page_icon="📝",
    layout="centered"
)

# Paths
SUBMISSIONS_FILE = Path("data/pending_submissions.json")
SUBMISSIONS_FILE.parent.mkdir(exist_ok=True)

def load_submissions():
    """Load existing submissions from JSON file."""
    if SUBMISSIONS_FILE.exists():
        with open(SUBMISSIONS_FILE) as f:
            return json.load(f)
    return []

def save_submission(submission):
    """Save a new submission to the JSON file."""
    submissions = load_submissions()
    submissions.append(submission)
    with open(SUBMISSIONS_FILE, 'w') as f:
        json.dump(submissions, f, indent=2)

# Back to chatbot button
if st.button("← Back to Chatbot", type="secondary"):
    st.switch_page("app.py")

# Header
st.title("📝 Suggest a Platform")

st.markdown("""
Help us grow our database! If you know of a platform serving People of Color
in tech or outdoor/travel spaces that we're missing, please submit it below.

**Your submission will be reviewed by our team before being added to the database.**
""")

st.divider()

# Submission form
with st.form("platform_submission", clear_on_submit=True):
    st.subheader("Platform Information")

    # Basic info
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input(
            "Platform Name *",
            placeholder="e.g., Outdoor Afro",
            help="Official name of the organization or platform"
        )
        platform_type = st.selectbox(
            "Platform Type *",
            ["", "Tech", "Outdoor/Travel"],
            help="Primary focus area"
        )

    with col2:
        website = st.text_input(
            "Website *",
            placeholder="https://example.com",
            help="Main website URL"
        )
        category = st.selectbox(
            "Category *",
            ["", "Nonprofit", "Community", "Company", "Network", "Media", "Event Series"],
            help="Type of organization"
        )

    # Focus area
    focus_area = st.text_input(
        "Focus Area *",
        placeholder="e.g., Black Women in Tech, Latinx Hiking",
        help="Specific community or demographic served"
    )

    # Description
    description = st.text_area(
        "Description *",
        placeholder="Brief description of what this platform does and who it serves...",
        help="2-3 sentences describing the platform's mission and offerings",
        height=100
    )

    # Additional details
    st.subheader("Additional Details (Optional)")

    col3, col4 = st.columns(2)
    with col3:
        founded = st.text_input(
            "Founded Year",
            placeholder="e.g., 2020",
            help="Year the platform was founded"
        )
        community_size = st.text_input(
            "Community Size",
            placeholder="e.g., 10K+ members",
            help="Approximate size of the community"
        )

    with col4:
        geographic_focus = st.text_input(
            "Geographic Focus",
            placeholder="e.g., United States, Global",
            help="Primary geographic region served"
        )

    key_programs = st.text_area(
        "Key Programs",
        placeholder="e.g., Mentorship, Job board, Annual conference",
        help="Main programs, services, or offerings",
        height=80
    )

    tags = st.text_input(
        "Tags",
        placeholder="e.g., black, tech, women, networking",
        help="Comma-separated keywords for search (lowercase)"
    )

    # Submitter info
    st.divider()
    st.subheader("Your Information (Optional)")

    col5, col6 = st.columns(2)
    with col5:
        submitter_name = st.text_input(
            "Your Name",
            placeholder="Optional"
        )
    with col6:
        submitter_email = st.text_input(
            "Your Email",
            placeholder="For updates on your submission"
        )

    # Submit button
    submitted = st.form_submit_button(
        "Submit Platform",
        use_container_width=True,
        type="primary"
    )

    if submitted:
        # Validate required fields
        if not all([name, platform_type, website, category, focus_area, description]):
            st.error("Please fill in all required fields (marked with *)")
        elif platform_type == "" or category == "":
            st.error("Please select a platform type and category")
        else:
            # Create submission
            submission = {
                "id": str(uuid.uuid4()),
                "submitted_at": datetime.now().isoformat(),
                "status": "pending",
                "platform": {
                    "name": name,
                    "type": platform_type,
                    "category": category,
                    "focus_area": focus_area,
                    "description": description,
                    "website": website.replace("https://", "").replace("http://", ""),
                    "founded": founded or "",
                    "community_size": community_size or "",
                    "key_programs": key_programs or "",
                    "geographic_focus": geographic_focus or "Not specified",
                    "tags": [tag.strip().lower() for tag in tags.split(",")] if tags else []
                },
                "submitter": {
                    "name": submitter_name or "Anonymous",
                    "email": submitter_email or ""
                }
            }

            # Save submission
            try:
                save_submission(submission)
                st.success(f"""
                ✅ **Thank you for your submission!**

                **{name}** has been submitted for review. Our team will review it and
                add it to the database if it meets our criteria.
                """)

                if submitter_email:
                    st.info(f"📧 We'll send updates to **{submitter_email}**")
            except Exception as e:
                st.error(f"Error saving submission: {e}")

# Show submission stats
st.divider()
submissions = load_submissions()
pending_count = len([s for s in submissions if s.get("status") == "pending"])

col_a, col_b, col_c = st.columns(3)
with col_a:
    st.metric("Total Submissions", len(submissions))
with col_b:
    st.metric("Pending Review", pending_count)
with col_c:
    approved_count = len([s for s in submissions if s.get("status") == "approved"])
    st.metric("Approved", approved_count)

# Guidelines
with st.expander("📋 Submission Guidelines"):
    st.markdown("""
    **What we're looking for:**

    ✅ **Do submit:**
    - Active platforms serving People of Color
    - Tech communities, outdoor/travel groups, or networking platforms
    - Organizations with clear mission and programs
    - Platforms with verifiable online presence

    ❌ **Don't submit:**
    - Individual social media accounts (unless official org presence)
    - Inactive or defunct organizations
    - Platforms not focused on PoC communities
    - Duplicate submissions

    **Review process:**
    1. Submissions are reviewed by our team
    2. We verify the platform is active and legitimate
    3. Approved platforms are added to the database within 1-2 weeks
    4. You'll receive an email update if you provided your email
    """)
