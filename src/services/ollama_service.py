"""Ollama LLM service wrapper."""

import logging
import time
import requests
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class OllamaService:
    """Service for communicating with local Ollama LLM."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3",
        timeout_seconds: int = 30,
        max_retries: int = 3,
        retry_backoff_multiplier: float = 2.0
    ):
        """
        Initialize Ollama service.
        
        Args:
            base_url: Ollama API base URL
            model: Model name to use
            timeout_seconds: Request timeout in seconds
            max_retries: Number of retry attempts on failure
            retry_backoff_multiplier: Backoff multiplier for retries
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_multiplier = retry_backoff_multiplier

    def generate(self, prompt: str, timeout_override: Optional[int] = None) -> Tuple[bool, str]:
        """
        Generate text from prompt with retry logic.
        
        Args:
            prompt: Input prompt for the model
            timeout_override: Optional per-call timeout (overrides self.timeout_seconds)
            
        Returns:
            Tuple of (success: bool, response: str)
        """
        effective_timeout = timeout_override if timeout_override is not None else self.timeout_seconds

        for attempt in range(self.max_retries):
            try:
                backoff_delay = (2 ** attempt) if attempt > 0 else 0
                if backoff_delay > 0:
                    logger.warning(f"Retry attempt {attempt + 1}/{self.max_retries} after {backoff_delay}s delay")
                    time.sleep(backoff_delay)

                response = requests.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                    },
                    timeout=effective_timeout
                )

                if response.status_code == 200:
                    data = response.json()
                    generated_text = data.get("response", "").strip()
                    logger.debug(f"Generated text length: {len(generated_text)} chars")
                    return True, generated_text

                elif response.status_code == 404:
                    error_msg = f"Model '{self.model}' not found. Available: {self._get_available_models()}"
                    logger.error(error_msg)
                    return False, error_msg

                else:
                    error_msg = f"Ollama API error: {response.status_code} - {response.text}"
                    logger.warning(f"Attempt {attempt + 1}/{self.max_retries}: {error_msg}")

            except requests.exceptions.Timeout:
                error_msg = f"Ollama timeout ({effective_timeout}s)"
                logger.warning(f"Attempt {attempt + 1}/{self.max_retries}: {error_msg}")

            except requests.exceptions.ConnectionError as e:
                error_msg = f"Cannot connect to Ollama at {self.base_url}: {e}"
                logger.warning(f"Attempt {attempt + 1}/{self.max_retries}: {error_msg}")

            except Exception as e:
                error_msg = f"Unexpected error: {e}"
                logger.warning(f"Attempt {attempt + 1}/{self.max_retries}: {error_msg}")

        return False, f"Failed after {self.max_retries} attempts"


    def _get_available_models(self) -> str:
        """Get list of available models from Ollama."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                models = [m["name"] for m in response.json().get("models", [])]
                return ", ".join(models) if models else "None"
        except Exception as e:
            logger.debug(f"Could not fetch available models: {e}")
        return "Unable to fetch"

    def is_available(self) -> bool:
        """Check if Ollama is available and responsive."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"Ollama connectivity check failed: {e}")
            return False
