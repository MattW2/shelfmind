import streamlit as st
import pandas as pd
import os
import base64
import html
import logging
import requests
import importlib
from datetime import datetime
from dotenv import load_dotenv

# Configure basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Import and hot-reload custom modules
import database
import opds_client
import ai_helper

importlib.reload(database)
importlib.reload(opds_client)
importlib.reload(ai_helper)

# Load environment variables
load_dotenv()

@st.cache_data(show_spinner=False, ttl=3600)
def get_book_cover_base64(cover_url, username, password):
    """Caches and returns base64 data URI of a basic-auth protected cover URL."""
    if not cover_url:
        return None
    try:
        auth_creds = (username, password) if username else None
        response = requests.get(cover_url, auth=auth_creds, timeout=10)
        if response.status_code == 200:
            encoded = base64.b64encode(response.content).decode("utf-8")
            return f"data:image/jpeg;base64,{encoded}"
    except Exception as e:
        logger.debug(f"Failed to fetch cover image {cover_url}: {e}")
    return None

# Page configuration
st.set_page_config(
    page_title="ShelfMind | AI Library Assistant",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize database
database.init_db()

# Load custom CSS stylesheet
css_path = os.path.join(os.path.dirname(__file__), "static", "styles.css")
if os.path.exists(css_path):
    with open(css_path, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# App Title Header
st.markdown("""
<div class="header-container">
    <h1 class="header-title">📚 ShelfMind</h1>
    <p class="header-subtitle">Intelligent library companion: analyze series sequences, discover missing volumes, clean metadata, and generate recommendations</p>
</div>
""", unsafe_allow_html=True)

# Navigation
st.sidebar.image("https://img.icons8.com/isometric/512/books.png", width=120)
st.sidebar.markdown("### Navigation")
page = st.sidebar.radio(
    "Go to:",
    ["Dashboard & Sync", "Library Explorer", "Series Analyzer", "AI Recommendations", "AI Metadata Cleaner"]
)

st.sidebar.markdown("---")
st.sidebar.markdown("### AI Model Settings")
selected_model = st.sidebar.selectbox(
    "Select Gemini Model:",
    [
        "gemini-3.5-flash-lite",
        "gemini-3.7-flash",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash",
        "gemini-3.1-pro-preview"
    ],
    index=0,
    help="Select the Gemini model variant for library analysis and recommendations."
)

# Helper to check if credentials are set
calibre_user = os.getenv("CALIBRE_USERNAME", "").strip()
gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
calibre_url = os.getenv("CALIBRE_URL", "").strip()

env_missing = (
    not calibre_url or 
    "your-calibre-web-instance" in calibre_url or
    not calibre_user or 
    calibre_user in ("your_username", "your_username_here") or
    not gemini_key or 
    gemini_key in ("your_gemini_api_key", "your_api_key_here")
)

if env_missing:
    st.sidebar.warning("⚠️ Credentials are not configured in your `.env` file. Please update it to enable library sync and AI features.")

# ----------------- PAGE 1: DASHBOARD & SYNC -----------------
if page == "Dashboard & Sync":
    st.markdown("### Library Statistics")
    
    total_books = database.get_total_books_count()
    series_list = database.get_series_list()
    total_series = len(series_list)
    last_sync = database.get_last_sync_time()
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{total_books}</div>
            <div class="stat-label">Total Books Cached</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{total_series}</div>
            <div class="stat-label">Unique Series</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col3:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value" style="font-size: 1.6rem; padding-top: 15px; padding-bottom: 15px;">
                {last_sync if last_sync else 'Never'}
            </div>
            <div class="stat-label">Last Synced Cache</div>
        </div>
        """, unsafe_allow_html=True)
        
    st.markdown("---")
    st.markdown("### Synchronize Cache with Calibre-Web")
    st.markdown("""
    This will pull book metadata from your Calibre-Web server via the OPDS protocol into the local SQLite database.
    The synchronization runs non-destructively using a staging table, preserving your current cache until the new sync completes.
    """)
    
    if st.button("🔄 Sync Library Now", type="primary"):
        if env_missing:
            st.error("Please configure the `.env` file credentials first!")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Dynamic estimate based on current cached count or fallback
            estimated_total = max(100, total_books if total_books > 0 else 950)
            
            def sync_progress_callback(count, message):
                if "Stage 1" in message:
                    progress_val = min(0.90, (count / estimated_total) * 0.90) if estimated_total > 0 else 0.5
                else:
                    progress_val = 0.95
                progress_bar.progress(progress_val)
                status_text.info(f"🔄 {message}")
            
            try:
                with st.spinner("Connecting to Calibre-Web and syncing..."):
                    synced_count = opds_client.sync_library(sync_progress_callback)
                progress_bar.progress(1.0)
                st.balloons()
                st.success(f"Successfully synchronized! Cached {synced_count} books in the local SQLite database.")
                st.rerun()
            except Exception as e:
                st.error(f"Sync failed: {e}")

# ----------------- PAGE 2: LIBRARY EXPLORER -----------------
elif page == "Library Explorer":
    st.markdown("### Search & Filter Library")
    
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        search_query = st.text_input("🔍 Search by title, author, series, or tags:")
    with c2:
        categories = ["All Genres/Tags"] + database.get_all_categories()
        selected_cat = st.selectbox("Filter by Category/Tag:", categories)
    with c3:
        series_only = st.checkbox("Show Series Only", value=False)
        
    # Query database using optimized SQL count and pagination
    cat_filter = None if selected_cat == "All Genres/Tags" else selected_cat
    total_matches = database.count_books(
        query=search_query if search_query else None,
        category=cat_filter,
        series_only=series_only
    )
    
    st.markdown(f"Found **{total_matches}** books matching your criteria.")
    
    if total_matches > 0:
        view_mode = st.radio("Display Mode:", ["Visual Cards", "Data Table"], horizontal=True)
        
        books_per_page = 20
        total_pages = max(1, (total_matches - 1) // books_per_page + 1)
        
        if total_pages > 1:
            current_page = st.number_input("Page:", min_value=1, max_value=total_pages, value=1)
        else:
            current_page = 1
            
        start_idx = (current_page - 1) * books_per_page
        
        page_books = database.search_books(
            query=search_query if search_query else None,
            category=cat_filter,
            series_only=series_only,
            limit=books_per_page,
            offset=start_idx
        )
        
        if view_mode == "Visual Cards":
            username = os.getenv("CALIBRE_USERNAME", "").strip()
            password = os.getenv("CALIBRE_PASSWORD", "").strip()
            
            for book in page_books:
                cover_url = book.get("cover_url")
                cover_img = get_book_cover_base64(cover_url, username, password)
                if not cover_img:
                    cover_img = "https://images.unsplash.com/photo-1543002588-bfa74002ed7e?auto=format&fit=crop&q=80&w=120&h=180"
                    
                series_info = ""
                if book.get("series"):
                    idx_str = f" #{book['series_index']}" if book.get("series_index") is not None else ""
                    series_safe = html.escape(str(book["series"]))
                    series_info = f'<div class="book-series">Series: {series_safe}{html.escape(idx_str)}</div>'
                    
                tags_info = ""
                if book.get("categories"):
                    for tag in book["categories"].split(",")[:6]:
                        tag_clean = tag.strip()
                        if tag_clean:
                            tags_info += f'<span class="tag-badge">{html.escape(tag_clean)}</span>'
                        
                desc = book.get("description") or "No description available."
                title_escaped = html.escape(book.get('title') or 'Untitled')
                author_escaped = html.escape(book.get('authors') or 'Unknown')
                desc_escaped = html.escape(desc)
                
                st.markdown(f"""
                <div class="book-card">
                    <img src="{cover_img}" class="book-cover" onerror="this.src='https://images.unsplash.com/photo-1543002588-bfa74002ed7e?w=100&h=150&fit=crop';"/>
                    <div class="book-info">
                        <div>
                            <h4 class="book-title">{title_escaped}</h4>
                            <p class="book-author">by {author_escaped}</p>
                            {series_info}
                        </div>
                        <div>
                            <p class="book-description">{desc_escaped}</p>
                            <div class="book-tags">{tags_info}</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
        else: # Data Table view
            all_table_books = database.search_books(
                query=search_query if search_query else None,
                category=cat_filter,
                series_only=series_only,
                limit=1000,
                offset=0
            )
            df = pd.DataFrame(all_table_books)
            display_cols = ["title", "authors", "series", "series_index", "publisher", "published", "categories"]
            available_cols = [c for c in display_cols if c in df.columns]
            df_display = df[available_cols]
            df_display.columns = [c.capitalize().replace("_", " ") for c in available_cols]
            st.dataframe(df_display, width="stretch")
            
    else:
        st.info("No books found matching search terms. Trigger a library sync on the Dashboard page if your cache is empty.")

# ----------------- PAGE 3: SERIES ANALYZER -----------------
elif page == "Series Analyzer":
    st.markdown("### AI Series Sequence Analyzer")
    st.markdown("Analyze your library to identify missing volumes in a series sequence.")
    
    def show_analysis_results(result):
        st.success("AI Analysis Completed!")
        
        if result.has_missing_books:
            st.markdown(f"#### ⚠️ Missing Volumes Detected (Main Sequence size: {result.total_books_in_series} books)")
            missing_list = []
            for book in result.missing_books:
                missing_list.append({
                    "Volume": book.volume_number,
                    "Title": book.title,
                    "Published Year": book.published_year if book.published_year else "Unknown",
                    "Summary": book.summary
                })
            missing_df = pd.DataFrame(missing_list).sort_values("Volume")
            st.dataframe(missing_df, width="stretch", hide_index=True)
        else:
            st.markdown("#### 🎉 Series Complete!")
            st.balloons()
            st.info(f"Gemini reports that your library has all major sequence books for this series (Total main sequence size: {result.total_books_in_series} books).")
            
        st.markdown("##### Detailed AI Analysis Summary")
        st.info(result.analysis_summary)

    analysis_mode = st.radio(
        "Choose analysis mode:",
        ["Browse Calibre Series (Mapped)", "Ad-hoc Series Finder (AI Discovery)"],
        horizontal=True
    )
    
    if analysis_mode == "Browse Calibre Series (Mapped)":
        series_list = database.get_series_list()
        
        if not series_list:
            st.warning("No series found in your cached library. Please sync your library first!")
        else:
            series_names = [s["series"] for s in series_list]
            selected_series = st.selectbox("Select a series to analyze:", series_names)
            
            owned_books = database.get_series_books(selected_series)
            st.markdown(f"#### Books in library for series: **{selected_series}**")
            
            owned_df = pd.DataFrame(owned_books)
            owned_display = owned_df[["series_index", "title", "authors", "published"]].sort_values("series_index")
            owned_display.columns = ["Vol #", "Book Title", "Authors", "Published Date"]
            st.dataframe(owned_display, width="stretch", hide_index=True)
            
            st.markdown("---")
            
            if st.button("🤖 Analyze Series Sequence with AI", type="primary", key="sync_series_btn"):
                if env_missing:
                    st.error("Please configure your GEMINI_API_KEY in the `.env` file first.")
                else:
                    with st.spinner(f"Querying Gemini to check publication history of '{selected_series}'..."):
                        try:
                            result = ai_helper.find_missing_series_books(selected_series, owned_books, model_name=selected_model)
                            show_analysis_results(result)
                        except Exception as e:
                            st.error(f"Failed to analyze series: {e}")
                            
    else: # Ad-hoc Series Finder (AI Discovery)
        st.markdown("##### Define a series based on a quick title/author search in your library:")
        keyword = st.text_input("Type a keyword to search (e.g. 'arthur' or 'pout-pout'):", value="arthur")
        
        if keyword:
            matched_books = database.search_books(query=keyword, limit=100)
            
            if not matched_books:
                st.info(f"No books found in library matching '{keyword}'.")
            else:
                st.markdown(f"#### Matched Books in Library ({len(matched_books)})")
                matched_df = pd.DataFrame(matched_books)
                matched_display = matched_df[["title", "authors", "series", "series_index"]].fillna("")
                matched_display.columns = ["Book Title", "Authors", "Calibre Series", "Calibre Vol #"]
                st.dataframe(matched_display, width="stretch", hide_index=True)
                
                st.markdown("---")
                
                if st.button("🤖 Discover Series & Find Missing Books with AI", type="primary", key="adhoc_series_btn"):
                    if env_missing:
                        st.error("Please configure your GEMINI_API_KEY in the `.env` file first.")
                    else:
                        with st.spinner(f"Using Gemini to discover series and check sequence from matched books..."):
                            try:
                                result = ai_helper.find_missing_from_book_list(matched_books, model_name=selected_model)
                                show_analysis_results(result)
                            except Exception as e:
                                st.error(f"Failed to analyze ad-hoc series: {e}")

# ----------------- PAGE 4: AI RECOMMENDATIONS -----------------
elif page == "AI Recommendations":
    st.markdown("### AI-Powered Book Recommendations")
    st.markdown("""
    Tell the AI what types of books you want to read. The AI will look at your current library to understand your reading taste, 
    recommend similar books, and **filter out books you already own** to provide fresh suggestions.
    """)
    
    total_cached = database.get_total_books_count()
    if total_cached == 0:
        st.warning("Please synchronize your library first to let the AI know what books you already own.")
    else:
        rec_source = st.radio(
            "Base recommendations on:",
            ["A Specific Genre/Category in Library", "A Book You Enjoyed", "Custom Theme Description"]
        )
        
        target_prompt = ""
        sample_books = []
        
        if rec_source == "A Specific Genre/Category in Library":
            categories = database.get_all_categories()
            selected_cat = st.selectbox("Choose a category/tag:", categories)
            target_prompt = f"Genre: {selected_cat}"
            sample_books = database.search_books(category=selected_cat, limit=35)
            
        elif rec_source == "A Book You Enjoyed":
            book_title_search = st.text_input("Search for the book title:")
            matching_books = database.search_books(query=book_title_search if book_title_search else None, limit=10)
            
            if book_title_search and matching_books:
                book_options = {f"{b['title']} by {b['authors']}": b for b in matching_books}
                selected_opt = st.selectbox("Select the exact book:", list(book_options.keys()))
                target_book = book_options[selected_opt]
                target_prompt = f"Similar to the book: '{target_book['title']}' by {target_book['authors']}"
                
                sample_books = database.search_books(query=target_book['authors'].split(',')[0], limit=20)
                sample_books.append(target_book)
            elif book_title_search:
                st.warning("No matching books found in your library database.")
                
        else: # Custom prompt
            custom_input = st.text_input(
                "Describe what you are looking for (e.g. 'cyberpunk murder mystery with artificial intelligence'):"
            )
            target_prompt = custom_input
            sample_books = database.search_books(limit=40)
            
        st.markdown("---")
        
        if st.button("✨ Generate AI Recommendations", type="primary"):
            if not target_prompt:
                st.error("Please specify your recommendation criteria first.")
            elif env_missing:
                st.error("Please configure your GEMINI_API_KEY in the `.env` file first.")
            else:
                with st.spinner(f"Analyzing library and generating tailored recommendations for '{target_prompt}'..."):
                    try:
                        result = ai_helper.get_book_recommendations(target_prompt, sample_books, model_name=selected_model)
                        st.success("Recommendations Generated!")
                        
                        for i, rec in enumerate(result.recommendations):
                            tags = "".join(f'<span class="tag-badge">{html.escape(t.strip())}</span>' for t in rec.genre_tags)
                            rec_title = html.escape(rec.title)
                            rec_author = html.escape(rec.author)
                            rec_desc = html.escape(rec.description)
                            rec_reason = html.escape(rec.reason)
                            
                            st.markdown(f"""
                            <div class="rec-card">
                                <span class="rec-match">{rec.estimated_match_percentage}% Match</span>
                                <h4 class="rec-title">{i+1}. {rec_title}</h4>
                                <p class="rec-author">by {rec_author}</p>
                                <p class="rec-description">{rec_desc}</p>
                                <div class="rec-reason"><strong>AI Recommendation Rationale:</strong> {rec_reason}</div>
                                <div style="margin-top:8px;">{tags}</div>
                            </div>
                            """, unsafe_allow_html=True)
                            
                        st.markdown("#### 📚 Reader Taste Insights")
                        st.info(result.overall_insight)
                        
                    except Exception as e:
                        st.error(f"Failed to generate recommendations: {e}")

# ----------------- PAGE 5: AI METADATA CLEANER -----------------
elif page == "AI Metadata Cleaner":
    st.markdown("### 🧼 AI Library Metadata Cleaner")
    st.markdown("""
    Use AI to clean and enrich your book catalog. Proactively identify formatting issues, standardise author spelling, 
    discover missing series details, and add relevant genre tags.
    
    You can search multiple terms sequentially to build a **Cleanup Queue**, review the list, and then process the entire batch at once.
    """)
    
    if "cleanup_queue" not in st.session_state:
        st.session_state.cleanup_queue = {}
    if "cleanup_errors" not in st.session_state:
        st.session_state.cleanup_errors = []
    if "cleanup_success_msg" not in st.session_state:
        st.session_state.cleanup_success_msg = None
        
    total_cached = database.get_total_books_count()
    if total_cached == 0:
        st.warning("Please synchronize your library first to load books.")
    else:
        # Step 1: Search & Build Queue
        st.markdown("#### 1. Search & Select Books to Clean")
        search_col, count_col = st.columns([3, 1])
        with search_col:
            clean_search = st.text_input("Search library (e.g. type 'arthur', 'pout-pout', or leave empty for recent additions):", "")
        with count_col:
            max_books = st.number_input("Search Limit:", min_value=5, max_value=200, value=100)
            
        candidate_books = database.search_books(query=clean_search if clean_search else None, limit=max_books)
        
        if candidate_books:
            st.markdown(f"**Found {len(candidate_books)} books matching your query:**")
            
            selected_books_options = st.multiselect(
                "Select books from results to add to queue:",
                options=candidate_books,
                format_func=lambda b: f"{b['title']} by {b['authors']} (Series: {b['series'] or 'None'})",
                key="candidate_multiselect"
            )
            
            col_add1, col_add2 = st.columns([1, 1])
            with col_add1:
                if st.button("➕ Add Selected to Queue", width="stretch"):
                    if selected_books_options:
                        for b in selected_books_options:
                            st.session_state.cleanup_queue[b["id"]] = b
                        st.success(f"Added {len(selected_books_options)} books to queue.")
                        st.rerun()
                    else:
                        st.warning("No books selected.")
            with col_add2:
                if st.button("➕ Add All Matched to Queue", width="stretch"):
                    for b in candidate_books:
                        st.session_state.cleanup_queue[b["id"]] = b
                    st.success(f"Added all {len(candidate_books)} books to queue.")
                    st.rerun()
        else:
            st.info("No matching books found for your query.")
            
        st.markdown("---")
        
        # Step 2: Show and Manage Queue
        st.markdown(f"#### 📋 Analysis Queue ({len(st.session_state.cleanup_queue)} books)")
        
        if "clean_books_removed_msg" in st.session_state and st.session_state.clean_books_removed_msg:
            st.info(st.session_state.clean_books_removed_msg)
            st.session_state.clean_books_removed_msg = None
            
        if st.session_state.cleanup_success_msg:
            st.success(st.session_state.cleanup_success_msg)
            st.session_state.cleanup_success_msg = None
            
        if st.session_state.cleanup_errors:
            for err in st.session_state.cleanup_errors:
                st.error(err)
            st.session_state.cleanup_errors = []
            
        if not st.session_state.cleanup_queue:
            st.info("Your cleanup queue is currently empty. Use the search block above to add books to the queue.")
        else:
            queue_list = list(st.session_state.cleanup_queue.values())
            queue_df = pd.DataFrame(queue_list)[["title", "authors", "series", "categories"]]
            queue_df.fillna("None", inplace=True)
            queue_df.columns = ["Book Title", "Authors", "Series", "Tags"]
            st.dataframe(queue_df, width="stretch", hide_index=True)
            
            col_q1, col_q2 = st.columns([1, 3])
            with col_q1:
                if st.button("🗑️ Clear Queue", width="stretch"):
                    st.session_state.cleanup_queue = {}
                    st.session_state.metadata_suggestions = None
                    st.session_state.analysis_inputs = None
                    st.session_state.clean_books_removed_msg = None
                    st.success("Queue cleared.")
                    st.rerun()
            with col_q2:
                if st.button("🤖 Run AI Metadata Analysis on Queue", type="primary", width="stretch"):
                    if env_missing:
                        st.error("Please configure your GEMINI_API_KEY in the `.env` file first.")
                    else:
                        with st.spinner("Analyzing queue metadata with Gemini..."):
                            try:
                                result = ai_helper.suggest_metadata_cleanup(queue_list, model_name=selected_model)
                                st.session_state.metadata_suggestions = result.corrections
                                st.session_state.analysis_inputs = {b["id"]: b for b in queue_list}
                                
                                suggested_book_ids = {corr.book_id for corr in result.corrections}
                                clean_books = [b for b in queue_list if b["id"] not in suggested_book_ids]
                                
                                for cb in clean_books:
                                    if cb["id"] in st.session_state.cleanup_queue:
                                        del st.session_state.cleanup_queue[cb["id"]]
                                        
                                if clean_books:
                                    st.session_state.clean_books_removed_msg = f"✨ Gemini found no issues with {len(clean_books)} books, so they were removed from the queue: " + ", ".join([f"'{b['title']}'" for b in clean_books])
                                else:
                                    st.session_state.clean_books_removed_msg = None
                                    
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed to analyze metadata: {e}")
                                
        if "metadata_suggestions" not in st.session_state:
            st.session_state.metadata_suggestions = None
        if "analysis_inputs" not in st.session_state:
            st.session_state.analysis_inputs = None
            
        if st.session_state.metadata_suggestions is not None:
            st.markdown("---")
            if not st.session_state.metadata_suggestions:
                st.success("🎉 Gemini reports that all books in the queue have perfect, clean, and complete metadata!")
            else:
                st.markdown("#### 3. Review and Approve Suggestions")
                st.markdown("Toggle the checkboxes to select which corrections to write back to Calibre-Web.")
                
                selected_corrections = []
                
                col_actions1, col_actions2 = st.columns([1, 4])
                with col_actions1:
                    select_all = st.checkbox("Select All Suggestions", value=True)
                
                for idx, corr in enumerate(st.session_state.metadata_suggestions):
                    original_book = st.session_state.analysis_inputs.get(corr.book_id)
                    if not original_book:
                        continue
                        
                    cb_key = f"corr_cb_{corr.book_id}_{idx}"
                    title_orig_safe = html.escape(corr.title_original)
                    reason_safe = html.escape(corr.reason)
                    
                    st.markdown(f"""
                    <div class="suggestion-card">
                        <h5 class="suggestion-title">Suggestion #{idx+1}: {title_orig_safe}</h5>
                        <p class="suggestion-reason"><strong>Reason:</strong> {reason_safe}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    col_prop, col_orig, col_arrow, col_sugg = st.columns([1.5, 4, 0.5, 4])
                    
                    changes_list = []
                    if corr.title_original != corr.title_suggested:
                        changes_list.append(("Title", corr.title_original, corr.title_suggested))
                    if corr.authors_original != corr.authors_suggested:
                        changes_list.append(("Authors", corr.authors_original, corr.authors_suggested))
                    if (corr.series_original or "") != (corr.series_suggested or ""):
                        changes_list.append(("Series", corr.series_original or "None", corr.series_suggested or "None"))
                    if corr.series_index_original != corr.series_index_suggested:
                        changes_list.append(("Vol #", str(corr.series_index_original) or "None", str(corr.series_index_suggested) or "None"))
                    if (corr.categories_original or "") != (corr.categories_suggested or ""):
                        changes_list.append(("Tags", corr.categories_original or "None", corr.categories_suggested or "None"))
                        
                    for prop, orig_val, sugg_val in changes_list:
                        with col_prop:
                            st.write(f"**{prop}**")
                        with col_orig:
                            st.write(f"`{orig_val}`")
                        with col_arrow:
                            st.write("➡️")
                        with col_sugg:
                            st.write(f"`{sugg_val}`")
                            
                    approved = st.checkbox("Approve this correction", value=select_all, key=cb_key)
                    if approved:
                        selected_corrections.append((corr, original_book))
                        
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                st.markdown("---")
                
                if st.button("🚀 Apply Approved Changes", type="primary"):
                    if not selected_corrections:
                        st.warning("No corrections selected for update.")
                    else:
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        success_count = 0
                        error_count = 0
                        errors_list = []
                        
                        # Helper mapping for DRY updates
                        field_diffs = [
                            ("title", lambda c: c.title_original, lambda c: c.title_suggested),
                            ("authors", lambda c: c.authors_original, lambda c: c.authors_suggested),
                            ("series", lambda c: c.series_original or "", lambda c: c.series_suggested or ""),
                            ("series_index", lambda c: c.series_index_original, lambda c: c.series_index_suggested),
                            ("categories", lambda c: c.categories_original or "", lambda c: c.categories_suggested or ""),
                        ]
                        
                        try:
                            # Use single session context manager for the entire batch
                            with opds_client.calibre_web_session() as (session, csrf_token, base_url):
                                for i, (corr, book) in enumerate(selected_corrections):
                                    status_text.text(f"Updating '{corr.title_original}' ({i+1}/{len(selected_corrections)})...")
                                    int_id = opds_client.extract_calibre_integer_id(book.get("cover_url"), book.get("download_url"))
                                    
                                    if not int_id:
                                        err_msg = f"Failed to determine server integer ID for '{corr.title_original}'"
                                        errors_list.append(err_msg)
                                        error_count += 1
                                        continue
                                        
                                    book_has_error = False
                                    for field_name, get_orig, get_sugg in field_diffs:
                                        orig_val = get_orig(corr)
                                        sugg_val = get_sugg(corr)
                                        
                                        if orig_val != sugg_val:
                                            try:
                                                opds_client.update_book_field_with_session(
                                                    session, csrf_token, base_url, int_id, field_name, sugg_val
                                                )
                                                database.update_book_metadata(book["id"], field_name, sugg_val)
                                            except Exception as e:
                                                book_has_error = True
                                                err_msg = f"Failed to update {field_name} for '{corr.title_original}': {e}"
                                                errors_list.append(err_msg)
                                                
                                    if not book_has_error:
                                        success_count += 1
                                        if book["id"] in st.session_state.cleanup_queue:
                                            del st.session_state.cleanup_queue[book["id"]]
                                    else:
                                        error_count += 1
                                        
                                    progress_bar.progress((i + 1) / len(selected_corrections))
                                    
                        except Exception as e:
                            errors_list.append(f"Authentication/Connection session error: {e}")
                            
                        st.session_state.cleanup_errors = errors_list
                        st.session_state.cleanup_success_msg = f"Successfully updated {success_count} books ({error_count} encountered errors)."
                        st.session_state.metadata_suggestions = None
                        st.session_state.analysis_inputs = None
                        st.rerun()
