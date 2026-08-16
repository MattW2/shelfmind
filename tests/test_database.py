import pytest
import sqlite3
import os
import tempfile
import database

@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Uses a temporary SQLite database for tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name
        
    monkeypatch.setattr(database, "DB_FILE", temp_db_path)
    database.init_db()
    
    yield temp_db_path
    
    if os.path.exists(temp_db_path):
        try:
            os.remove(temp_db_path)
        except Exception:
            pass

def test_database_initialization():
    assert database.get_total_books_count() == 0
    assert database.get_last_sync_time() is None

def test_save_and_search_books():
    books = [
        {
            "id": "urn:uuid:1",
            "title": "Arthur Babysits",
            "authors": "Marc Brown",
            "series": "Arthur Adventure Series",
            "series_index": 1.0,
            "categories": "Children, Animals",
            "description": "Arthur babysits twins.",
            "publisher": "Little, Brown",
            "published": "1992",
            "language": "en",
            "cover_url": "http://example.com/cover/101",
            "download_url": "http://example.com/download/101/epub"
        },
        {
            "id": "urn:uuid:2",
            "title": "Dune",
            "authors": "Frank Herbert",
            "series": "Dune Chronicles",
            "series_index": 1.0,
            "categories": "Science Fiction, Space",
            "description": "Epic desert planet sci-fi.",
            "publisher": "Chilton",
            "published": "1965",
            "language": "en",
            "cover_url": "http://example.com/cover/102",
            "download_url": "http://example.com/download/102/epub"
        }
    ]
    
    database.save_books_batch(books)
    assert database.get_total_books_count() == 2
    
    # Test text search
    res = database.search_books(query="Babysits")
    assert len(res) == 1
    assert res[0]["title"] == "Arthur Babysits"
    
    # Test category search
    res_sci_fi = database.search_books(category="Science Fiction")
    assert len(res_sci_fi) == 1
    assert res_sci_fi[0]["title"] == "Dune"
    
    # Test count function
    assert database.count_books(query="Arthur") == 1
    assert database.count_books(series_only=True) == 2

def test_update_book_metadata_safe():
    book = {
        "id": "urn:uuid:123",
        "title": "Old Title",
        "authors": "Old Author",
        "series": None,
        "series_index": None,
        "categories": "OldTag",
        "description": "Desc",
        "publisher": None,
        "published": None,
        "language": None,
        "cover_url": None,
        "download_url": None
    }
    database.save_books_batch([book])
    
    # Safe update
    database.update_book_metadata("urn:uuid:123", "title", "New Clean Title")
    updated = database.search_books(query="New Clean Title")
    assert len(updated) == 1
    assert updated[0]["title"] == "New Clean Title"

def test_update_book_metadata_sql_injection_prevented():
    book = {
        "id": "urn:uuid:999",
        "title": "Test Book",
        "authors": "Tester",
        "last_synced": "2026-01-01"
    }
    database.save_books_batch([book])
    
    # SQL injection attempt on column name should raise ValueError
    with pytest.raises(ValueError):
        database.update_book_metadata("urn:uuid:999", "title = 'pwned', authors", "malicious")

def test_staging_table_and_atomic_swap():
    database.create_staging_table()
    staged_book = {
        "id": "urn:uuid:staged_1",
        "title": "Staged Book",
        "authors": "Staged Author"
    }
    database.save_books_batch([staged_book], table_name="books_staging")
    
    # Live table should still be empty
    assert database.get_total_books_count() == 0
    
    # Swap staging to live
    database.swap_staging_to_live()
    assert database.get_total_books_count() == 1
    assert database.search_books()[0]["title"] == "Staged Book"
