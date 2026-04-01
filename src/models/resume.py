"""Resume data models."""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class ResumeData:
    """Resume information extracted from JSON."""
    name: str
    skills: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Resume:
    """Resume file and data."""
    json_path: str
    data: Optional[ResumeData] = None
    
    def is_loaded(self) -> bool:
        """Check if resume data is loaded."""
        return self.data is not None
