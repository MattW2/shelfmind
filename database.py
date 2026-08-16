import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_FILE = "library_cache.db"

ALLOWED_UPDATE_COLUMNS = {
    "title", "authors", "publisher", "published", "language",
    "categories", "series", "series_index", "description",
    "cover_url", "download_url"
}

def get_db_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn=None):
    """Initializes the database schema."""
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True
        
    cursor = conn.cursor()
    
    # Books cache table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT,
            publisher TEXT,
            published TEXT,
            language TEXT,
            categories TEXT,
            series TEXT,
            series_index REAL,
            description TEXT,
            cover_url TEXT,
            download_url TEXT,
            last_synced TEXT NOT NULL
        )
    """)
    
    # Indexing for performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_title ON books(title)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_series ON books(series)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_authors ON books(authors)")
    
    conn.commit()
    if close_after:
        conn.close()

def clear_database():
    """Deletes all books from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM books")
    conn.commit()
    conn.close()

def create_staging_table():
    """Creates a clean staging table for atomic sync operations."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS books_staging")
    cursor.execute("""
        CREATE TABLE books_staging (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT,
            publisher TEXT,
            published TEXT,
            language TEXT,
            categories TEXT,
            series TEXT,
            series_index REAL,
            description TEXT,
            cover_url TEXT,
            download_url TEXT,
            last_synced TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def save_books_batch(books_data, table_name="books"):
    """Saves a batch of books to the specified table using transaction for speed."""
    if not books_data:
        return
        
    # Prevent SQL injection on table_name
    if table_name not in ("books", "books_staging"):
        raise ValueError(f"Invalid table name: {table_name}")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    sync_time = datetime.now().isoformat()
    
    insert_query = f"""
        INSERT OR REPLACE INTO {table_name} (
            id, title, authors, publisher, published, language, 
            categories, series, series_index, description, 
            cover_url, download_url, last_synced
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    records = []
    for b in books_data:
        records.append((
            b.get("id"),
            b.get("title"),
            b.get("authors"),
            b.get("publisher"),
            b.get("published"),
            b.get("language"),
            b.get("categories"),
            b.get("series"),
            b.get("series_index"),
            b.get("description"),
            b.get("cover_url"),
            b.get("download_url"),
            sync_time
        ))
        
    cursor.executemany(insert_query, records)
    conn.commit()
    conn.close()

def swap_staging_to_live():
    """Atomically swaps books_staging to books table and creates indices."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS books_old")
    cursor.execute("CREATE TABLE IF NOT EXISTS books (id TEXT PRIMARY KEY, title TEXT NOT NULL, authors TEXT, publisher TEXT, published TEXT, language TEXT, categories TEXT, series TEXT, series_index REAL, description TEXT, cover_url TEXT, download_url TEXT, last_synced TEXT NOT NULL)")
    cursor.execute("ALTER TABLE books RENAME TO books_old")
    cursor.execute("ALTER TABLE books_staging RENAME TO books")
    cursor.execute("DROP TABLE IF EXISTS books_old")
    
    # Re-apply indexes on the new live table
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_title ON books(title)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_series ON books(series)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_authors ON books(authors)")
    
    conn.commit()
    conn.close()

def drop_staging_table():
    """Drops the staging table if sync failed."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS books_staging")
    cursor.execute("DROP TABLE IF EXISTS books_old")
    conn.commit()
    conn.close()

def get_total_books_count():
    """Returns the total number of books in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM books")
        row = cursor.fetchone()
        count = row[0] if row else 0
    except sqlite3.OperationalError:
        count = 0
    finally:
        conn.close()
    return count

def get_last_sync_time():
    """Returns the most recent last_synced timestamp."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT MAX(last_synced) FROM books")
        row = cursor.fetchone()
        if row and row[0]:
            try:
                dt = datetime.fromisoformat(row[0])
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.debug(f"Failed to parse datetime {row[0]}: {e}")
                return row[0]
    except sqlite3.OperationalError as e:
        logger.debug(f"Database table missing during get_last_sync_time: {e}")
    finally:
        conn.close()
    return None

def search_books(query=None, category=None, series_only=False, limit=100, offset=0):
    """Searches and filters cached books."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    sql = "SELECT * FROM books"
    params = []
    conditions = []
    
    if query:
        search_pattern = f"%{query.strip()}%"
        conditions.append("(title LIKE ? OR authors LIKE ? OR series LIKE ? OR categories LIKE ?)")
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern])
        
    if category and category != "All Genres/Tags":
        cat_pattern = f"%{category.strip()}%"
        conditions.append("categories LIKE ?")
        params.append(cat_pattern)
        
    if series_only:
        conditions.append("series IS NOT NULL AND series != ''")
        
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
        
    # Sort order: series name + index if series exists, otherwise title
    sql += " ORDER BY CASE WHEN series IS NULL OR series = '' THEN 1 ELSE 0 END, series, series_index, title"
    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def count_books(query=None, category=None, series_only=False):
    """Returns the count of matching books without fetching rows."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    sql = "SELECT COUNT(*) FROM books"
    params = []
    conditions = []
    
    if query:
        search_pattern = f"%{query.strip()}%"
        conditions.append("(title LIKE ? OR authors LIKE ? OR series LIKE ? OR categories LIKE ?)")
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern])
        
    if category and category != "All Genres/Tags":
        cat_pattern = f"%{category.strip()}%"
        conditions.append("categories LIKE ?")
        params.append(cat_pattern)
        
    if series_only:
        conditions.append("series IS NOT NULL AND series != ''")
        
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
        
    cursor.execute(sql, params)
    row = cursor.fetchone()
    count = row[0] if row else 0
    conn.close()
    return count

def get_series_list(search_query=None):
    """Returns unique series names and their book counts."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    sql = """
        SELECT series, COUNT(*) as book_count, MIN(authors) as author
        FROM books
        WHERE series IS NOT NULL AND series != ''
    """
    params = []
    
    if search_query:
        sql += " AND series LIKE ?"
        params.append(f"%{search_query.strip()}%")
        
    sql += " GROUP BY series ORDER BY series COLLATE NOCASE"
    
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_series_books(series_name):
    """Returns all books belonging to a specific series, ordered by index."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM books WHERE series = ? ORDER BY series_index, title",
        (series_name,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_categories():
    """Returns a list of all unique category tags sorted alphabetically."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT categories FROM books WHERE categories IS NOT NULL")
    rows = cursor.fetchall()
    conn.close()
    
    cats = set()
    for row in rows:
        val = row[0]
        if val:
            for part in val.split(','):
                part_clean = part.strip()
                if part_clean:
                    cats.add(part_clean)
    return sorted(list(cats))

def update_book_metadata(book_id, param, new_value):
    """Updates a single metadata field of a book in the local SQLite database safely."""
    # Map tag parameter to categories in SQLite
    db_param = param
    if param in ("tags", "categories"):
        db_param = "categories"
        
    # Whitelist column check to prevent SQL injection
    if db_param not in ALLOWED_UPDATE_COLUMNS:
        raise ValueError(f"Invalid column name: {db_param}")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = f"UPDATE books SET {db_param} = ? WHERE id = ?"
    cursor.execute(query, (new_value, book_id))
    conn.commit()
    conn.close()
