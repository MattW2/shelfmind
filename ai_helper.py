import os
import logging
import functools
from typing import List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)
load_dotenv()

# Fallback sequence if primary model encounters errors
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.7-flash", "gemini-2.5-flash", "gemini-3.1-flash-lite"]

# Define Pydantic Models for Structured Output

class MissingBook(BaseModel):
    title: str = Field(description="The official title of the missing book in the series")
    volume_number: float = Field(description="The official volume/index number in the series (e.g. 1.0, 2.5, 3.0)")
    published_year: Optional[int] = Field(description="The year the book was published (if known)")
    summary: str = Field(description="A brief 1-2 sentence description of what this book is about")

class SeriesAnalysisResult(BaseModel):
    series_name: str = Field(description="Name of the book series analyzed")
    total_books_in_series: int = Field(description="Total official books in the main series sequence")
    has_missing_books: bool = Field(description="True if there are missing books, False if the series is complete in the library")
    missing_books: List[MissingBook] = Field(description="List of books that are missing from the user's library")
    analysis_summary: str = Field(description="Detailed textual explanation of what is missing, ordering, and interesting context about the series")


class RecommendedBook(BaseModel):
    title: str = Field(description="Title of the recommended book")
    author: str = Field(description="Author of the recommended book")
    genre_tags: List[str] = Field(description="Genres or category tags for this book")
    description: str = Field(description="Brief summary of the book")
    reason: str = Field(description="Why this book is recommended based on the user's library contents or requested types")
    estimated_match_percentage: int = Field(description="A rating from 1 to 100 of how closely this matches the requested type")

class RecommendationsResult(BaseModel):
    recommendations: List[RecommendedBook] = Field(description="List of recommended books")
    overall_insight: str = Field(description="A short paragraph offering insight into the user's reading preferences and this set of recommendations")


@functools.lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Initializes and returns a cached GenAI client."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set. Please check your .env file.")
    return genai.Client(api_key=api_key)


def _generate_with_fallback(client: genai.Client, model_name: str, contents: str, response_schema, temperature: float = 0.2):
    """Executes structured generate_content with automatic fallback if primary model fails."""
    candidates = [model_name] + [m for m in FALLBACK_MODELS if m != model_name]
    last_error = None
    
    for candidate_model in candidates:
        try:
            logger.info(f"Querying Gemini using model: {candidate_model}")
            response = client.models.generate_content(
                model=candidate_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=temperature,
                ),
            )
            if response.parsed is not None:
                return response.parsed
            else:
                logger.warning(f"Model {candidate_model} returned unparseable structured output. Raw: {response.text[:200]}")
        except Exception as e:
            logger.warning(f"Model {candidate_model} failed with error: {e}")
            last_error = e
            
    raise RuntimeError(f"All model attempts failed. Last error: {last_error}")


def find_missing_series_books(series_name: str, existing_books: List[dict], model_name: str = "gemini-3.5-flash-lite") -> SeriesAnalysisResult:
    """Uses Gemini to identify missing books in a series based on what's in the library."""
    client = get_client()
    
    existing_books_str = ""
    if existing_books:
        for b in existing_books:
            title = b.get("title", "Unknown Title")
            idx = b.get("series_index")
            idx_str = f" [Vol {idx}]" if idx is not None else ""
            existing_books_str += f"- {title}{idx_str}\n"
    else:
        existing_books_str = "(No books found in this series currently)\n"
        
    prompt = f"""
    You are an expert library assistant and bibliographic verification specialist.
    I want to analyze the book series: "{series_name}".
    
    Here is a list of the books I CURRENTLY have in my library for this series:
    {existing_books_str}
    
    Please perform the following verification and analysis:
    1. Cross-reference and verify the series against Goodreads (https://www.goodreads.com/series/...) and Hardcover (https://hardcover.app/series/...) as well as official publisher bibliographies to identify the real, published books in the main series sequence of "{series_name}". If Goodreads is not able to be accessed, Hardcover (https://hardcover.app/) may be used.
    2. STRICT FACTUAL ACCURACY: Every title you return MUST be a real, verifiable, published book documented on Goodreads (https://www.goodreads.com/) or Hardcover (https://hardcover.app/). DO NOT hallucinate, guess, or invent fake titles or volume numbers under any circumstances.
    3. Compare the verified official Goodreads/Hardcover series sequence with my library list.
    4. Identify which main sequence books are MISSING from my library. Ignore spin-offs, novellas, or omnibus editions unless they are considered official numbered entries in the primary sequence.
    5. Provide the total count of books in the main sequence, the exact verified list of missing books with publication years and summaries, and a detailed summary explaining the series order, what is missing, and general series status.
    """
    
    return _generate_with_fallback(client, model_name, prompt, SeriesAnalysisResult, temperature=0.0)


def find_missing_from_book_list(books: List[dict], model_name: str = "gemini-3.5-flash-lite") -> SeriesAnalysisResult:
    """Identifies the series a given list of books belongs to and finds missing volumes."""
    client = get_client()
    
    books_str = ""
    for idx, b in enumerate(books):
        title = b.get("title", "Unknown Title")
        author = b.get("authors", "Unknown Author")
        books_str += f"- '{title}' by {author}\n"
        
    prompt = f"""
    You are an expert library assistant and bibliographic verification specialist.
    I have a collection of books from my library that I believe belong to a series, but they might not be formally grouped or marked as a series:
    {books_str}
    
    Please perform the following verification and analysis:
    1. Identify the official book series (e.g., Marc Brown's "Arthur Adventures" series or "Arthur chapter books") that these books belong to by cross-referencing Goodreads (https://www.goodreads.com/) or Hardcover (https://hardcover.app/). If Goodreads is not able to be accessed, Hardcover (https://hardcover.app/) may be used. If they belong to multiple related series by the same author, focus on the primary main sequence.
    2. Cross-reference and verify the official main sequence of published books against Goodreads (https://www.goodreads.com/series/...) or Hardcover (https://hardcover.app/series/...).
    3. STRICT FACTUAL ACCURACY: Every title you return MUST be a real, verifiable, published book documented on Goodreads (https://www.goodreads.com/) or Hardcover (https://hardcover.app/). DO NOT hallucinate, guess, or invent fake book titles or volume numbers.
    4. Compare the verified official list with the list of books I have.
    5. Identify which volumes are missing from my library collection.
    6. Provide structured output with the series name, the total number of books in the main sequence, the verified list of missing books, and a detailed summary explaining the series, the ordering, and what is missing.
    """
    
    return _generate_with_fallback(client, model_name, prompt, SeriesAnalysisResult, temperature=0.0)


def get_book_recommendations(
    target_type: str, 
    sample_owned_books: List[dict],
    model_name: str = "gemini-3.5-flash-lite"
) -> RecommendationsResult:
    """Uses Gemini to suggest similar books based on genres, types, or specific selections, excluding owned ones."""
    client = get_client()
    
    owned_books_str = ""
    for b in sample_owned_books:
        title = b.get("title", "Unknown Title")
        author = b.get("authors", "Unknown Author")
        series = b.get("series")
        series_str = f" (Series: {series})" if series else ""
        owned_books_str += f"- {title} by {author}{series_str}\n"
        
    prompt = f"""
    You are an expert reading advisor and book recommender.
    The user wants suggestions for books of type/genre/topic: "{target_type}".
    
    Here is a sample of books the user ALREADY owns in their library:
    {owned_books_str}
    
    Please do the following:
    1. Recommend 5 to 7 books that are highly relevant to the requested type: "{target_type}".
    2. IMPORTANT: Do NOT recommend any books that are already in the list of books the user owns above! We want fresh reading recommendations.
    3. For each recommended book, specify:
       - Title
       - Author
       - Genre/category tags
       - A brief description of the book
       - A detailed explanation of why it is recommended based on the user's request and owned books
       - Estimated match percentage (1 to 100)
    4. Provide an overall insight paragraph about the user's reading taste and why this collection of recommendations fits perfectly.
    """
    
    return _generate_with_fallback(client, model_name, prompt, RecommendationsResult, temperature=0.7)


class MetadataCorrection(BaseModel):
    book_id: str = Field(description="The unique book ID (e.g., urn:uuid:...)")
    title_original: str = Field(description="The original title of the book")
    title_suggested: str = Field(description="The suggested cleaned title of the book")
    authors_original: str = Field(description="The original author(s) of the book")
    authors_suggested: str = Field(description="The suggested cleaned author(s) of the book")
    series_original: Optional[str] = Field(description="The original series name")
    series_suggested: Optional[str] = Field(description="The suggested cleaned series name")
    series_index_original: Optional[float] = Field(description="The original series index")
    series_index_suggested: Optional[float] = Field(description="The suggested cleaned series index")
    categories_original: Optional[str] = Field(description="The original categories/tags")
    categories_suggested: Optional[str] = Field(description="The suggested cleaned categories/tags (comma-separated)")
    reason: str = Field(description="Short, clear explanation of why this change is suggested (e.g., 'Removed publisher tags from author field')")

class LibraryCleanupResult(BaseModel):
    corrections: List[MetadataCorrection] = Field(description="List of suggested metadata corrections")


def _suggest_metadata_single_batch(books: List[dict], model_name: str) -> List[MetadataCorrection]:
    """Helper to analyze a single batch of up to 30 books."""
    client = get_client()
    
    books_str = ""
    for b in books:
        books_str += f"""
        Book ID: {b.get('id')}
        Title: {b.get('title')}
        Authors: {b.get('authors')}
        Series: {b.get('series') or 'None'}
        Series Index: {b.get('series_index') or 'None'}
        Categories: {b.get('categories') or 'None'}
        Description: {repr((b.get('description') or '')[:150])}
        ---
        """
        
    prompt = f"""
    You are an expert digital librarian and catalog metadata cleaner.
    I have a collection of books in my library that have messy, corrupted, or inconsistent metadata.
    
    Here is the list of books to clean:
    {books_str}
    
    Please analyze each book and suggest corrections or additions/enhancements for:
    1. Inconsistent author names (e.g., "Peet| Bill" should be "Bill Peet", "Redbank| Tennant| author" should be "Tennant Redbank").
    2. Extraneous publisher/editor suffix markings in author fields (e.g. "Uncle Amon" might be okay, but "Uncle Amon. author; HarperCollins. pbl" should be just "Uncle Amon").
    3. Formatting typos in titles (e.g. weird characters, extra spaces, accidental ISBN tags, or bracketed files).
    4. Missing or inconsistent series names and volume numbers: If a book has no series defined, but the title, description, or your general bibliographic knowledge indicates it belongs to a series (e.g., "Arthur", "Junie B. Jones", "Magic Tree House", "The Expanse", "Culture"), please suggest the correct official series name and the volume number (series_index) for it.
    5. Missing or thin tags/categories: If the book has few tags, recommend 3 to 6 high-quality, relevant genres or subject tags (e.g., "Fantasy", "Science Fiction", "Bedtime Stories", "Humor") based on its title and description to enrich the catalog.
    6. Incorrect or messy tags (e.g. clean up duplicate tags, resolve weird archive URLs or raw filenames to actual genre tags).
    
    Provide a list of corrections. Cross-reference real publisher, Goodreads (https://www.goodreads.com/), or Hardcover (https://hardcover.app/) entries to ensure all suggested titles, series names, and volume indices match real-world publications. IMPORTANT: If a book's metadata is already perfect and clean (including having a robust set of tags and accurate series metadata if applicable), do NOT include it in the corrections list. Only suggest corrections for books that actually need cleaning or enhancement.
    """
    
    res: LibraryCleanupResult = _generate_with_fallback(client, model_name, prompt, LibraryCleanupResult, temperature=0.0)
    return res.corrections


def suggest_metadata_cleanup(books: List[dict], model_name: str = "gemini-3.5-flash-lite", batch_size: int = 30) -> LibraryCleanupResult:
    """Uses Gemini to identify and suggest metadata cleanup for books, automatically chunking large lists."""
    if not books:
        return LibraryCleanupResult(corrections=[])
        
    all_corrections = []
    
    # Process in chunks of batch_size
    for i in range(0, len(books), batch_size):
        chunk = books[i:i + batch_size]
        logger.info(f"Processing metadata cleanup chunk {i // batch_size + 1}/{(len(books) - 1) // batch_size + 1} ({len(chunk)} books)")
        chunk_corrections = _suggest_metadata_single_batch(chunk, model_name)
        all_corrections.extend(chunk_corrections)
        
    return LibraryCleanupResult(corrections=all_corrections)
