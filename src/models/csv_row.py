"""CSV row data models."""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class CSVRow:
    """Parsed CSV row."""
    email: str
    title: Optional[str] = None
    description: Optional[str] = None
    row_index: int = 0
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def job_context(self) -> str:
        """Combine title and description for LLM."""
        parts = [p for p in [self.title, self.description] if p]
        return "\n".join(parts)
