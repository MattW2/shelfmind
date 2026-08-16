import pytest
from unittest.mock import MagicMock
import ai_helper
from ai_helper import (
    MissingBook,
    SeriesAnalysisResult,
    RecommendedBook,
    RecommendationsResult,
    MetadataCorrection,
    LibraryCleanupResult
)

def test_missing_book_schema():
    book = MissingBook(
        title="Arthur's New Puppy",
        volume_number=2.0,
        published_year=2001,
        summary="Arthur gets a new puppy."
    )
    assert book.title == "Arthur's New Puppy"
    assert book.volume_number == 2.0

def test_series_analysis_result_schema():
    res = SeriesAnalysisResult(
        series_name="Arthur Adventure Series",
        total_books_in_series=41,
        has_missing_books=True,
        missing_books=[
            MissingBook(
                title="Arthur's New Puppy",
                volume_number=2.0,
                published_year=2001,
                summary="Arthur gets a new puppy."
            )
        ],
        analysis_summary="Main sequence has 41 books."
    )
    assert len(res.missing_books) == 1
    assert res.has_missing_books is True

def test_metadata_cleanup_schema():
    corr = MetadataCorrection(
        book_id="urn:uuid:123",
        title_original="Arthur Babysits (Series)",
        title_suggested="Arthur Babysits",
        authors_original="Brown| Marc",
        authors_suggested="Marc Brown",
        series_original=None,
        series_suggested="Arthur Adventure Series",
        series_index_original=None,
        series_index_suggested=1.0,
        categories_original=None,
        categories_suggested="Children, Animals",
        reason="Cleaned author syntax and extracted series."
    )
    assert corr.title_suggested == "Arthur Babysits"
    assert corr.authors_suggested == "Marc Brown"

def test_generate_with_fallback_success(monkeypatch):
    mock_client = MagicMock()
    mock_response = MagicMock()
    expected_result = SeriesAnalysisResult(
        series_name="Test Series",
        total_books_in_series=5,
        has_missing_books=False,
        missing_books=[],
        analysis_summary="Complete series."
    )
    mock_response.parsed = expected_result
    mock_client.models.generate_content.return_value = mock_response
    
    result = ai_helper._generate_with_fallback(mock_client, "gemini-3.1-pro-preview", "prompt", SeriesAnalysisResult)
    assert result == expected_result
    assert mock_client.models.generate_content.call_count == 1

def test_generate_with_fallback_retry_on_error(monkeypatch):
    mock_client = MagicMock()
    
    # First model fails, second model succeeds
    mock_response_success = MagicMock()
    expected_result = RecommendationsResult(
        recommendations=[],
        overall_insight="Good taste."
    )
    mock_response_success.parsed = expected_result
    
    mock_client.models.generate_content.side_effect = [
        Exception("429 Quota Exceeded"),
        mock_response_success
    ]
    
    result = ai_helper._generate_with_fallback(mock_client, "gemini-3.1-pro-preview", "prompt", RecommendationsResult)
    assert result == expected_result
    assert mock_client.models.generate_content.call_count == 2
