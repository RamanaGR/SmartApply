"""Email data models."""

from dataclasses import dataclass
from typing import List


@dataclass
class Email:
    """Email message structure."""
    recipient: str
    subject: str
    body: str
    
    def is_valid(self) -> bool:
        """Check if email has required fields."""
        return bool(self.recipient and self.subject and self.body)


@dataclass
class EmailValidationResult:
    """Email validation result."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
