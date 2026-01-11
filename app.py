"""
PoC Platforms Discovery - Streamlit Web Application

RAG-powered chatbot to help discover platforms for People of Color
in tech and outdoor/travel spaces.
"""

import streamlit as st
from src.core.chatbot import RAGChatbot
import config

# Page configuration
st.set_page_config(
    page_title=config.APP_TITLE,
    page_icon="🌿",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Enhanced CSS with vibrant earthy design
st.markdown("""
<style>
    /* Color palette - vibrant earth tones */
    :root {
        --primary-green: #2D5016;
        --accent-orange: #E07A5F;
        --warm-terracotta: #C1541B;
        --sage: #81A684;
        --forest: #3D5A3D;
        --cream: #F8F4E8;
        --sand: #EDE7D9;
        --clay: #A44827;
        --moss: #5F7A61;
        --sunset: #F2AA5C;

        /* Typography */
        --font-display: 'Iowan Old Style', Georgia, 'Times New Roman', serif;
        --font-body: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }

    /* Global styles */
    * {
        font-family: var(--font-body);
    }

    /* Main app background with texture */
    .stApp {
        background: linear-gradient(135deg, #F8F4E8 0%, #EDE7D9 50%, #E8DFC8 100%);
        background-attachment: fixed;
    }

    /* Header - elegant serif */
    h1 {
        font-family: var(--font-display) !important;
        color: #2D5016 !important;
        font-weight: 700 !important;
        letter-spacing: -0.5px !important;
        margin-bottom: 0.5rem !important;
        text-shadow: 0 2px 4px rgba(45, 80, 22, 0.1);
    }

    /* Subheaders */
    h2, h3 {
        font-family: var(--font-display) !important;
        color: #3D5A3D !important;
        font-weight: 600 !important;
    }

    /* Body text */
    p, li, span, div {
        color: #2D3436;
        line-height: 1.7;
    }

    /* Links - warm with smooth transition */
    a {
        color: #C1541B;
        text-decoration: none;
        transition: all 0.3s ease;
        font-weight: 500;
        border-bottom: 2px solid transparent;
    }

    a:hover {
        color: #E07A5F;
        border-bottom: 2px solid #E07A5F;
    }

    /* Hero section with custom styling */
    .hero-text {
        font-size: 1.15rem;
        color: #3D5A3D;
        line-height: 1.8;
        margin: 1.5rem 0;
        font-weight: 400;
    }

    .hero-text strong {
        color: #2D5016;
        font-weight: 600;
    }

    /* Example queries card - vibrant */
    .examples-card {
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.95) 0%, rgba(248, 244, 232, 0.95) 100%);
        padding: 1.5rem;
        border-radius: 1rem;
        border: 2px solid #81A684;
        margin: 1.5rem 0;
        box-shadow: 0 4px 16px rgba(45, 80, 22, 0.12);
        position: relative;
        overflow: hidden;
    }

    .examples-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 6px;
        height: 100%;
        background: linear-gradient(180deg, #2D5016 0%, #81A684 100%);
    }

    .examples-card strong {
        color: #2D5016;
        font-size: 1.1rem;
        font-weight: 600;
        display: block;
        margin-bottom: 1rem;
    }

    .examples-card ul {
        list-style: none;
        padding-left: 0;
        margin: 0;
    }

    .examples-card li {
        color: #3D5A3D;
        padding: 0.6rem 0;
        padding-left: 1.5rem;
        position: relative;
        font-weight: 500;
        transition: all 0.2s ease;
    }

    .examples-card li::before {
        content: '→';
        position: absolute;
        left: 0;
        color: #C1541B;
        font-weight: bold;
        font-size: 1.2rem;
    }

    .examples-card li:hover {
        transform: translateX(4px);
        color: #2D5016;
    }

    /* Chat messages - using proper Streamlit 2025 selectors */
    [data-testid="stChatMessage"] {
        padding: 1.5rem !important;
        border-radius: 1.2rem !important;
        margin-bottom: 1.2rem !important;
        background: rgba(255, 255, 255, 0.95) !important;
        border: 2px solid rgba(129, 166, 132, 0.3) !important;
        box-shadow: 0 4px 12px rgba(45, 80, 22, 0.08) !important;
        transition: transform 0.2s ease, box-shadow 0.2s ease !important;
    }

    [data-testid="stChatMessage"]:hover {
        box-shadow: 0 6px 20px rgba(45, 80, 22, 0.12) !important;
        transform: translateY(-2px) !important;
    }

    [data-testid="stChatMessageContent"] p {
        color: #2D3436;
        margin-bottom: 0.8rem;
    }

    /* Chat input styling - Streamlit 2025 (minimal, clean) */
    [data-testid="stChatInput"] textarea {
        border-radius: 1.5rem !important;
        transition: border-color 0.2s ease !important;
    }

    [data-testid="stChatInput"] textarea:focus {
        outline: none !important;
    }

    /* Platform cards - rich, layered design */
    .platform-card {
        background: linear-gradient(135deg, #FFFFFF 0%, #F8F4E8 100%);
        padding: 1.5rem;
        border-radius: 1rem;
        margin: 1rem 0;
        border: 2px solid #E8DFC8;
        box-shadow:
            0 4px 12px rgba(45, 80, 22, 0.08),
            0 2px 4px rgba(45, 80, 22, 0.04);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;
    }

    .platform-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 5px;
        height: 100%;
        background: linear-gradient(180deg, #C1541B 0%, #E07A5F 100%);
        opacity: 0.8;
    }

    .platform-card:hover {
        transform: translateY(-4px) scale(1.01);
        box-shadow:
            0 12px 24px rgba(45, 80, 22, 0.15),
            0 4px 8px rgba(45, 80, 22, 0.08);
        border-color: #81A684;
    }

    .platform-name {
        font-family: 'Playfair Display', Georgia, serif;
        font-weight: 700;
        font-size: 1.3rem;
        color: #2D5016;
        margin-bottom: 0.5rem;
        letter-spacing: -0.3px;
    }

    .platform-type {
        display: inline-block;
        background: linear-gradient(135deg, #81A684 0%, #5F7A61 100%);
        color: white;
        padding: 0.4rem 1rem;
        border-radius: 2rem;
        font-size: 0.85rem;
        font-weight: 600;
        margin-bottom: 1rem;
        letter-spacing: 0.3px;
        box-shadow: 0 2px 8px rgba(95, 122, 97, 0.3);
    }

    .platform-description {
        color: #3D5A3D;
        line-height: 1.7;
        margin: 1rem 0;
        font-size: 0.95rem;
    }

    .platform-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        margin-top: 1rem;
        padding-top: 1rem;
        border-top: 1px solid rgba(129, 166, 132, 0.2);
    }

    .platform-meta strong {
        color: #5F7A61;
        font-weight: 600;
        font-size: 0.9rem;
    }

    .platform-card a {
        color: #C1541B;
        font-weight: 600;
        text-decoration: none;
        border-bottom: 2px solid transparent;
        transition: all 0.2s ease;
    }

    .platform-card a:hover {
        color: #E07A5F;
        border-bottom: 2px solid #E07A5F;
    }

    /* Expander - subtle when closed, vibrant when open */
    .streamlit-expanderHeader {
        background: rgba(255, 255, 255, 0.6);
        border: 2px solid rgba(129, 166, 132, 0.3);
        border-radius: 0.8rem;
        color: #3D5A3D !important;
        font-weight: 600;
        font-size: 0.95rem;
        padding: 0.8rem 1.2rem;
        transition: all 0.3s ease;
    }

    .streamlit-expanderHeader:hover {
        background: rgba(129, 166, 132, 0.1);
        border-color: rgba(129, 166, 132, 0.5);
        transform: translateX(4px);
    }

    .streamlit-expanderHeader p {
        color: #3D5A3D !important;
        margin: 0;
        font-weight: 600;
    }

    /* Expander when open */
    details[open] .streamlit-expanderHeader {
        background: linear-gradient(135deg, #2D5016 0%, #3D5A3D 100%);
        color: #FFFFFF !important;
        border-color: #2D5016;
        border-bottom-left-radius: 0;
        border-bottom-right-radius: 0;
        box-shadow: 0 4px 12px rgba(45, 80, 22, 0.2);
    }

    details[open] .streamlit-expanderHeader p {
        color: #FFFFFF !important;
    }

    .streamlit-expanderContent {
        background: rgba(255, 255, 255, 0.95);
        border: 2px solid #2D5016;
        border-top: none;
        border-bottom-left-radius: 0.8rem;
        border-bottom-right-radius: 0.8rem;
        padding: 1.5rem;
        box-shadow: 0 4px 12px rgba(45, 80, 22, 0.08);
    }

    /* Sidebar - warm texture */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #F8F4E8 0%, #EDE7D9 100%);
        border-right: 2px solid rgba(129, 166, 132, 0.3);
    }

    [data-testid="stSidebar"] h2 {
        color: #2D5016 !important;
        font-weight: 700;
        margin-bottom: 1.5rem;
    }

    [data-testid="stSidebar"] label {
        color: #3D5A3D !important;
        font-weight: 600;
        font-size: 0.95rem;
    }

    /* Buttons - vibrant CTAs */
    .stButton > button {
        background: linear-gradient(135deg, #C1541B 0%, #E07A5F 100%);
        color: white;
        border-radius: 0.8rem;
        border: none;
        padding: 0.7rem 2rem;
        font-weight: 600;
        letter-spacing: 0.3px;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: 0 4px 12px rgba(193, 84, 27, 0.3);
    }

    .stButton > button:hover {
        background: linear-gradient(135deg, #A44827 0%, #C1541B 100%);
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(193, 84, 27, 0.4);
    }

    .stButton > button:active {
        transform: translateY(0);
    }

    /* Chat input placeholder text */
    [data-testid="stChatInput"] textarea::placeholder {
        color: var(--sage);
        font-weight: 500;
    }

    /* Metrics - branded */
    [data-testid="stMetricValue"] {
        color: #C1541B;
        font-weight: 700;
        font-family: 'Playfair Display', Georgia, serif;
    }

    [data-testid="stMetricLabel"] {
        color: #5F7A61;
        font-weight: 600;
    }

    /* Dividers */
    hr {
        border: none;
        height: 2px;
        background: linear-gradient(90deg, transparent 0%, rgba(129, 166, 132, 0.3) 50%, transparent 100%);
        margin: 2rem 0;
    }

    /* Alerts - warm and informative */
    .stAlert {
        background: rgba(255, 255, 255, 0.95) !important;
        border-left: 4px solid #E07A5F !important;
        border-radius: 0.8rem;
        color: #2D3436 !important;
        box-shadow: 0 2px 8px rgba(224, 122, 95, 0.15);
    }

    /* Loading spinner */
    .stSpinner > div {
        border-color: #81A684 !important;
        border-right-color: transparent !important;
    }

    /* Select box */
    .stSelectbox > div > div {
        border-radius: 0.8rem;
        border: 2px solid rgba(129, 166, 132, 0.3);
        transition: all 0.2s ease;
    }

    .stSelectbox > div > div:hover {
        border-color: rgba(129, 166, 132, 0.6);
    }

    /* Slider */
    .stSlider > div > div > div {
        background: linear-gradient(90deg, #81A684 0%, #2D5016 100%);
    }

    /* Footer */
    .footer {
        text-align: center;
        margin-top: 3rem;
        padding: 2rem 1rem;
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.7) 0%, rgba(248, 244, 232, 0.7) 100%);
        border-radius: 1rem;
        border: 2px solid rgba(129, 166, 132, 0.2);
    }

    .footer-main {
        font-family: 'Playfair Display', Georgia, serif;
        font-size: 1.1rem;
        color: #2D5016;
        font-weight: 600;
        margin-bottom: 1rem;
    }

    .footer-links {
        font-size: 0.9rem;
    }

    .footer-links a {
        color: #C1541B;
        font-weight: 600;
        margin: 0 1rem;
        transition: all 0.2s ease;
    }

    .footer-links a:hover {
        color: #E07A5F;
    }

    /* ============================================
       ACCESSIBILITY IMPROVEMENTS (2025 Best Practices)
       ============================================ */

    /* Better focus indicators for keyboard navigation */
    button:focus-visible,
    a:focus-visible {
        outline: 3px solid var(--warm-terracotta) !important;
        outline-offset: 2px !important;
    }

    /* Improved contrast for better readability */
    [data-testid="stMarkdown"] a {
        text-decoration-line: underline;
        text-decoration-style: dotted;
        text-underline-offset: 3px;
    }

    /* ============================================
       RESPONSIVE DESIGN (Mobile-First)
       ============================================ */

    @media (max-width: 768px) {
        h1 {
            font-size: 2rem !important;
        }

        .platform-card, .examples-card {
            padding: 1rem;
            margin: 0.75rem 0;
        }

        [data-testid="stChatMessage"] {
            padding: 1rem !important;
        }

        .footer-links a {
            display: block;
            margin: 0.5rem 0;
        }
    }

    /* Reduced motion for accessibility */
    @media (prefers-reduced-motion: reduce) {
        *,
        *::before,
        *::after {
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
        }
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def initialize_chatbot():
    """Initialize chatbot (cached to avoid reloading on every interaction)."""
    try:
        chatbot = RAGChatbot(
            n_results=config.DEFAULT_TOP_K,
            conversation_memory=config.CONVERSATION_MEMORY_TURNS,
            enable_events=True  # Events now populated!
        )
        return chatbot
    except Exception as e:
        st.error(f"❌ Failed to initialize chatbot: {e}")
        raise


def display_platform_card(platform):
    """Display a platform as a rich, detailed card."""
    st.markdown(f"""
    <div class="platform-card">
        <div class="platform-name">{platform['name']}</div>
        <div class="platform-type">{platform['type']} · {platform['focus_area']}</div>
        <div class="platform-description">{platform['description']}</div>
        <div class="platform-meta">
            <div style="flex: 1;">
                <strong>Website</strong><br>
                <a href="https://{platform['website']}" target="_blank">{platform['website']}</a>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def display_event_card(event):
    """Display an event as a rich, detailed card."""
    # Format date nicely
    date_str = event.get('date', 'TBD')
    time_str = event.get('time', '')
    location_str = event.get('location', 'TBD')

    # Create event type badge color
    event_type = event.get('event_type', 'other')
    type_colors = {
        'conference': '#C1541B',
        'workshop': '#81A684',
        'meetup': '#E07A5F',
        'webinar': '#5F7A61',
        'other': '#3D5A3D'
    }
    badge_color = type_colors.get(event_type, '#3D5A3D')

    st.markdown(f"""
    <div class="platform-card" style="border-left: 4px solid {badge_color};">
        <div class="platform-name">🎉 {event['title']}</div>
        <div class="platform-type">
            <span style="background: {badge_color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; margin-right: 8px;">
                {event_type.upper()}
            </span>
            {event.get('org_name', 'Event')}
        </div>
        <div class="platform-description">{event.get('description', 'No description available')}</div>
        <div class="platform-meta">
            <div style="flex: 1;">
                <strong>📅 Date</strong><br>
                {date_str} {time_str}
            </div>
            <div style="flex: 1;">
                <strong>📍 Location</strong><br>
                {location_str}
            </div>
        </div>
        <div style="margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid rgba(129, 166, 132, 0.2);">
            <a href="{event.get('url', '#')}" target="_blank" style="display: inline-block; background: {badge_color}; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: 600; transition: opacity 0.2s;">
                Register / Learn More →
            </a>
        </div>
    </div>
    """, unsafe_allow_html=True)


def main():
    """Main Streamlit application."""

    # Header
    st.title("🌿 PoC Platforms Discovery")

    st.markdown("""
    <div class="hero-text">
        Discover vibrant communities and platforms created by and for People of Color
        in <strong>tech</strong> and <strong>outdoor/travel</strong> spaces.
    </div>
    """, unsafe_allow_html=True)

    # Example queries
    st.markdown("""
    <div class="examples-card">
        <strong>Try asking me:</strong>
        <ul>
            <li>"What communities exist for Black women in tech?"</li>
            <li>"Find me Latinx hiking groups"</li>
            <li>"Are there any upcoming Black tech conferences?"</li>
            <li>"What outdoor events are happening soon?"</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Check configuration
    errors = config.validate_config()
    if errors:
        with st.expander("⚙️ Configuration Notice", expanded=False):
            st.warning("No LLM API keys configured. Using fallback responses (still useful!).")
            st.info("""
            To enable AI-powered responses:
            1. Copy `.env.example` to `.env`
            2. Add at least one API key
            3. Restart the app
            """)

    # Initialize chatbot
    chatbot = initialize_chatbot()

    # Sidebar with options
    with st.sidebar:
        st.header("⚙️ Settings")

        # Type filter
        type_filter = st.selectbox(
            "Filter by type",
            ["All", "Tech", "Outdoor/Travel"],
            index=0
        )
        filter_value = None if type_filter == "All" else type_filter

        # Number of results
        n_results = st.slider(
            "Results per query",
            min_value=3,
            max_value=10,
            value=5
        )
        chatbot.n_results = n_results

        # Clear chat button
        if st.button("🗑️ Clear Chat History"):
            chatbot.clear_history()
            st.session_state.messages = []
            st.rerun()

        # Stats
        st.divider()
        st.markdown("### 📊 Database Stats")
        stats = chatbot.get_stats()

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Platforms", stats['retriever']['total_documents'], help="Total platforms in database")
        with col2:
            st.metric("Chat Turns", stats['conversation_turns'], help="Messages in current conversation")

        # Get event count from event store
        try:
            event_stats = chatbot.event_store.get_collection_stats() if chatbot.enable_events else None
            if event_stats:
                st.metric("Events", event_stats.get('total_events', 0), help="Upcoming events in database")
        except:
            pass  # Event store might not be initialized

        # Quick actions
        st.divider()
        st.markdown("### 🎯 Quick Actions")

        if st.button("📋 Browse All Platforms", use_container_width=True):
            st.session_state.browse_all_platforms = True

        if st.button("🎉 Browse All Events", use_container_width=True):
            st.session_state.browse_all_events = True

    # Initialize chat history in session state
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Handle "Browse All" actions
    if st.session_state.get("browse_all_platforms", False):
        st.divider()
        st.subheader("📋 All Platforms")

        # Auto-send query to chatbot
        browse_query = "List all platforms in the database"
        result = chatbot.chat(query=browse_query, include_sources=True)

        st.markdown(result["response"])

        if result.get("sources"):
            st.markdown(f"**Showing {len(result['sources'])} platforms:**")
            for platform in result["sources"]:
                display_platform_card(platform)

        # Reset flag
        st.session_state.browse_all_platforms = False

    if st.session_state.get("browse_all_events", False):
        st.divider()
        st.subheader("🎉 All Upcoming Events")

        # Auto-send query to chatbot
        browse_query = "Show me all upcoming events"
        result = chatbot.chat(query=browse_query, include_sources=True)

        st.markdown(result["response"])

        if result.get("events"):
            st.markdown(f"**Showing {len(result['events'])} events:**")
            for event in result["events"]:
                display_event_card(event)

        # Reset flag
        st.session_state.browse_all_events = False

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("Ask about PoC platforms..."):
        # Add user message to chat
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Searching platforms and events..."):
                result = chatbot.chat(
                    query=prompt,
                    type_filter=filter_value,
                    include_sources=True
                )

            # Display response
            st.markdown(result["response"])

            # Save assistant message
            st.session_state.messages.append({
                "role": "assistant",
                "content": result["response"],
                "sources": result.get("sources", []),
                "events": result.get("events", [])
            })

    # Footer
    st.divider()

    # Footer with functional links
    col_footer1, col_footer2, col_footer3 = st.columns(3)

    with col_footer1:
        # Use markdown link instead of button to avoid switch_page issues
        st.markdown(
            '<a href="/01_Suggest_Platform" target="_self" '
            'style="display: inline-block; width: 100%; text-align: center; padding: 0.5rem; '
            'background: linear-gradient(135deg, #C1541B 0%, #E07A5F 100%); color: white; '
            'border-radius: 0.5rem; text-decoration: none; font-weight: 600;">📝 Suggest a Platform</a>',
            unsafe_allow_html=True
        )

    with col_footer2:
        # GitHub repo link (update with your actual repo URL)
        st.markdown(
            '<a href="https://github.com/yourusername/afroadv-chatbot" target="_blank" '
            'style="display: inline-block; width: 100%; text-align: center; padding: 0.5rem; '
            'background: linear-gradient(135deg, #C1541B 0%, #E07A5F 100%); color: white; '
            'border-radius: 0.5rem; text-decoration: none; font-weight: 600;">🤝 Contribute</a>',
            unsafe_allow_html=True
        )

    with col_footer3:
        st.markdown(
            '<a href="https://github.com/yourusername/afroadv-chatbot/issues" target="_blank" '
            'style="display: inline-block; width: 100%; text-align: center; padding: 0.5rem; '
            'background: linear-gradient(135deg, #C1541B 0%, #E07A5F 100%); color: white; '
            'border-radius: 0.5rem; text-decoration: none; font-weight: 600;">🐛 Report Issue</a>',
            unsafe_allow_html=True
        )

    st.markdown("""
    <div style="text-align: center; margin-top: 2rem; padding: 1rem; color: #5F7A61; font-size: 0.9rem;">
        Built with care to uplift and connect PoC communities 💚
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
