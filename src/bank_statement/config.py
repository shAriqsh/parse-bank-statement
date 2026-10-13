import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai


def load_gemini_api_key(dotenv_path: Path | str | None = None) -> str:
    """Load GEMINI_API_KEY from environment or local .env file.

    Raises:
        ValueError: If GEMINI_API_KEY is not configured.
    """
    if dotenv_path is not None:
        load_dotenv(dotenv_path=dotenv_path)
    else:
        load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key or not api_key.strip():
        raise ValueError(
            "GEMINI_API_KEY or GOOGLE_API_KEY is not set. Please configure it in your environment or a .env file."
        )

    return api_key.strip()


def get_gemini_client(dotenv_path: Path | str | None = None) -> genai.Client:
    """Initialize and return a Google GenAI client instance."""
    api_key = load_gemini_api_key(dotenv_path=dotenv_path)
    return genai.Client(api_key=api_key)
