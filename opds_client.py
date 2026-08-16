import os
import re
import logging
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from contextlib import contextmanager
from dotenv import load_dotenv
import database

logger = logging.getLogger(__name__)

# XML Namespaces
NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'dcterms': 'http://purl.org/dc/terms/',
    'opds': 'http://opds-spec.org/2010/catalog',
    'xhtml': 'http://www.w3.org/1999/xhtml'
}

def clean_xml_string(content):
    """Removes invalid XML 1.0 control characters and sanitizes ampersands."""
    # Remove ASCII control characters (0x00-0x08, 0x0B, 0x0C, 0x0E-0x1F)
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', content)
    # Escape raw ampersands that aren't already part of an XML entity
    cleaned = re.sub(r'&(?!(\w+|#\d+|#[xX][a-fA-F0-9]+);)', '&amp;', cleaned)
    return cleaned

def parse_entry(entry, base_url):
    """Parses a single <entry> XML element and extracts book metadata."""
    title_el = entry.find('atom:title', NS)
    title = title_el.text.strip() if title_el is not None and title_el.text else "Untitled"
    
    id_el = entry.find('atom:id', NS)
    book_id = id_el.text.strip() if id_el is not None and id_el.text else ""
    
    # Extract authors (can be multiple)
    authors = []
    for author_el in entry.findall('atom:author', NS):
        name_el = author_el.find('atom:name', NS)
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())
    authors_str = ", ".join(authors) if authors else "Unknown Author"
    
    # Publisher
    pub_el = entry.find('atom:publisher/atom:name', NS)
    publisher = pub_el.text.strip() if pub_el is not None and pub_el.text else None
    
    # Published date
    published_el = entry.find('atom:published', NS)
    published = published_el.text.strip() if published_el is not None and published_el.text else None
    
    # Language
    lang_el = entry.find('dcterms:language', NS)
    language = lang_el.text.strip() if lang_el is not None and lang_el.text else None
    
    # Categories
    categories = []
    for cat_el in entry.findall('atom:category', NS):
        term = cat_el.get('term')
        if term:
            categories.append(term.strip())
    categories_str = ", ".join(categories) if categories else None
    
    # Links: cover and download URLs
    cover_url = None
    download_url = None
    
    for link_el in entry.findall('atom:link', NS):
        rel = link_el.get('rel')
        href = link_el.get('href')
        if not href:
            continue
            
        # Standard cover rels
        if rel in ('http://opds-spec.org/image', 'http://opds-spec.org/image/thumbnail'):
            # Calibre Web uses relative paths, make them absolute
            cover_url = urljoin(base_url, href)
            
        # Acquisition/download link
        elif rel == 'http://opds-spec.org/acquisition':
            # Pre-select EPUB or PDF over other formats if possible
            type_attr = link_el.get('type') or ''
            if 'epub' in type_attr.lower() or not download_url:
                download_url = urljoin(base_url, href)
                
    # Parse Series and Description from content
    series = None
    series_index = None
    description = None
    
    content_el = entry.find('atom:content', NS)
    if content_el is not None:
        # Extract text recursively
        content_text = "".join(content_el.itertext())
        
        # Regex for series matching: "SERIES: Series Name [Index]"
        series_match = re.search(r'SERIES:\s*(.*?)\s*\[([\d\.-]+)\]', content_text)
        if series_match:
            series = series_match.group(1).strip()
            try:
                series_index = float(series_match.group(2))
            except ValueError:
                series_index = None
                
        # Try to extract the description from <p> inside XHTML content
        p_el = content_el.find('.//xhtml:p', NS)
        if p_el is not None:
            description = "".join(p_el.itertext()).strip()
        else:
            # Fallback: take all text that doesn't start with SERIES:, TAGS:, or RATING:
            lines = [line.strip() for line in content_text.split('\n') if line.strip()]
            desc_lines = []
            for line in lines:
                if any(line.startswith(prefix) for prefix in ('SERIES:', 'TAGS:', 'RATING:')):
                    continue
                # Also ignore general custom column patterns "Column Name: value"
                if re.match(r'^[^:]+:\s*.*$', line) and not line.startswith('http'):
                    continue
                desc_lines.append(line)
            if desc_lines:
                description = "\n".join(desc_lines)
                
    # Fallback to summary if description is still empty
    if not description:
        summary_el = entry.find('atom:summary', NS)
        if summary_el is not None and summary_el.text:
            description = summary_el.text.strip()
            
    return {
        "id": book_id,
        "title": title,
        "authors": authors_str,
        "publisher": publisher,
        "published": published,
        "language": language,
        "categories": categories_str,
        "series": series,
        "series_index": series_index,
        "description": description,
        "cover_url": cover_url,
        "download_url": download_url
    }

def fetch_feed_page(url, auth_creds):
    """Fetches a single page and parses it, returning parsed books and next link."""
    response = requests.get(url, auth=auth_creds, timeout=15)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch OPDS page {url}. Status code: {response.status_code}")
        
    cleaned_xml = clean_xml_string(response.text)
    root = ET.fromstring(cleaned_xml)
    
    # Parse all books in this page
    base_url = response.url # absolute URL after redirects
    books = []
    for entry in root.findall('atom:entry', NS):
        book_info = parse_entry(entry, base_url)
        if book_info["id"]:
            books.append(book_info)
            
    # Find next page link if it exists
    next_link = None
    for link in root.findall('atom:link', NS):
        if link.get('rel') == 'next':
            next_href = link.get('href')
            if next_href:
                next_link = urljoin(base_url, next_href)
                break
                
    return books, next_link

def sync_library(progress_callback=None):
    """Downloads all books from the OPDS feed safely into staging and swaps to live."""
    database.init_db()
    load_dotenv()
    
    url = os.getenv("CALIBRE_URL", "").strip()
    if not url:
        raise ValueError("CALIBRE_URL is not set in .env")
        
    username = os.getenv("CALIBRE_USERNAME", "").strip()
    password = os.getenv("CALIBRE_PASSWORD", "").strip()
    auth_creds = (username, password) if username else None
    
    base_url = url.rstrip("/")
    
    if not base_url.endswith("/opds"):
        start_url = base_url + "/opds/new"
    else:
        start_url = base_url + "/new"
        
    current_url = start_url
    total_synced = 0
    pages_processed = 0
    
    # Create isolated staging table for non-destructive sync
    database.create_staging_table()
    
    if progress_callback:
        progress_callback(0, "Stage 1/2: Connecting to Calibre-Web...")
        
    try:
        while current_url:
            pages_processed += 1
            books, next_url = fetch_feed_page(current_url, auth_creds)
            
            # Save batch to staging
            database.save_books_batch(books, table_name="books_staging")
            total_synced += len(books)
            
            if progress_callback:
                progress_callback(total_synced, f"Stage 1/2: Synced {total_synced} books from library feed...")
                
            current_url = next_url
            
        # ----------------- STAGE 2: MAP SERIES DATA -----------------
        series_list_url = base_url + "/opds/series/letter/00"
        if progress_callback:
            progress_callback(total_synced, "Stage 2/2: Fetching series mapping...")
            
        try:
            response = requests.get(series_list_url, auth=auth_creds, timeout=15)
            if response.status_code == 200:
                cleaned = clean_xml_string(response.text)
                root = ET.fromstring(cleaned)
                series_entries = root.findall('atom:entry', NS)
                
                valid_series = []
                for entry in series_entries:
                    title_elem = entry.find('atom:title', NS)
                    title = title_elem.text if title_elem is not None else None
                    if title and title != "All" and len(title) > 1:
                        link_el = entry.find('atom:link', NS)
                        if link_el is not None:
                            valid_series.append((title, link_el.get('href')))
                
                conn = database.get_db_connection()
                cursor = conn.cursor()
                
                for s_idx, (series_name, series_href) in enumerate(valid_series):
                    series_url = urljoin(base_url, series_href)
                    if progress_callback:
                        progress_callback(total_synced, f"Stage 2/2: Mapping series '{series_name}' ({s_idx + 1}/{len(valid_series)})...")
                    
                    series_res = requests.get(series_url, auth=auth_creds, timeout=15)
                    if series_res.status_code == 200:
                        series_xml = clean_xml_string(series_res.text)
                        series_root = ET.fromstring(series_xml)
                        books_entries = series_root.findall('atom:entry', NS)
                        
                        for b_idx, book_entry in enumerate(books_entries):
                            title_elem = book_entry.find('atom:title', NS)
                            id_elem = book_entry.find('atom:id', NS)
                            if title_elem is None or id_elem is None:
                                continue
                            book_title = title_elem.text or ""
                            book_id = id_elem.text or ""
                            
                            inferred_index = b_idx + 1.0
                            title_match = re.search(r'#([\d\.]+)', book_title)
                            if title_match:
                                try:
                                    inferred_index = float(title_match.group(1))
                                except ValueError:
                                    pass
                                    
                            cursor.execute(
                                "UPDATE books_staging SET series = ?, series_index = ? WHERE id = ?",
                                (series_name, inferred_index, book_id)
                            )
                conn.commit()
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to map series details: {e}")
            
        # Swap staging table to live database atomically
        database.swap_staging_to_live()
        return total_synced
        
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        database.drop_staging_table()
        raise

@contextmanager
def calibre_web_session():
    """Context manager providing an authenticated Calibre-Web session and CSRF token."""
    load_dotenv()
    url = os.getenv("CALIBRE_URL", "").rstrip("/")
    username = os.getenv("CALIBRE_USERNAME", "").strip()
    password = os.getenv("CALIBRE_PASSWORD", "").strip()
    
    if not url:
        raise ValueError("CALIBRE_URL is not configured.")
        
    session = requests.Session()
    login_url = url + "/login"
    login_res = session.get(login_url, timeout=15)
    
    csrf_token = None
    token_match = re.search(r'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"', login_res.text)
    if not token_match:
        token_match = re.search(r'value="([^"]+)"\s+name="csrf_token"', login_res.text)
    if not token_match:
        token_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_res.text)
        
    if not token_match:
        raise Exception("Could not retrieve login CSRF token from calibre-web server.")
        
    csrf_token = token_match.group(1)
    
    login_post = session.post(login_url, data={
        "username": username,
        "password": password,
        "csrf_token": csrf_token
    }, timeout=15)
    
    if login_post.status_code != 200 or ("Login" in login_post.text and "<title>Calibre-Web" in login_post.text):
        raise Exception("Failed to authenticate with calibre-web server. Check credentials.")
        
    index_res = session.get(url + "/", timeout=15)
    ajax_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', index_res.text)
    if not ajax_csrf:
        ajax_csrf = re.search(r'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"', index_res.text)
    if not ajax_csrf:
        ajax_csrf = re.search(r'meta\s+name="csrf-token"\s+content="([^"]+)"', index_res.text)
        
    active_csrf = ajax_csrf.group(1) if ajax_csrf else csrf_token
    
    try:
        yield session, active_csrf, url
    finally:
        session.close()

def extract_calibre_integer_id(cover_url, download_url):
    """Extracts internal integer book ID from cover or download link."""
    match = None
    if cover_url:
        match = re.search(r'/cover/(\d+)', cover_url)
    if not match and download_url:
        match = re.search(r'/download/(\d+)/', download_url)
    if not match:
        return None
    return int(match.group(1))

def update_book_field_with_session(session, csrf_token, base_url, int_id, param, new_value):
    """Updates a single field using an existing authenticated session."""
    endpoint_param = param
    if param in ("categories", "tags"):
        endpoint_param = "tags"
        
    ajax_url = f"{base_url}/ajax/editbooks/{endpoint_param}"
    payload = {
        "pk": int_id,
        "value": new_value if new_value is not None else ""
    }
    headers = {"X-CSRFToken": csrf_token}
    
    res = session.post(ajax_url, data=payload, headers=headers, timeout=15)
    if res.status_code != 200:
        raise Exception(f"Server returned status code {res.status_code}: {res.text}")
        
    res_json = res.json()
    if isinstance(res_json, dict):
        if not res_json.get("success") and "newValue" not in res_json:
            raise Exception(res_json.get("msg") or "Failed to update metadata on server.")
    elif isinstance(res_json, list):
        if len(res_json) > 0 and not res_json[0].get("success"):
            raise Exception(res_json[0].get("msg") or "Failed to update metadata on server.")
            
    return True

def update_book_metadata_on_server(book_id, cover_url, download_url, param, new_value):
    """One-off wrapper for single field updates."""
    int_id = extract_calibre_integer_id(cover_url, download_url)
    if not int_id:
        raise Exception(f"Could not extract Calibre integer ID for book {book_id}")
        
    with calibre_web_session() as (session, csrf_token, base_url):
        return update_book_field_with_session(session, csrf_token, base_url, int_id, param, new_value)
