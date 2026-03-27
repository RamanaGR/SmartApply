"""General validators for SmartApply."""

import re
from typing import Optional
from src.utils.regex import EmailRegex


class EmailValidator:
    """Email format and content validation."""
    
    @staticmethod
    def is_valid_format(email: str) -> bool:
        """Check if email has valid format."""
        return EmailRegex.is_valid(email)
    
    @staticmethod
    def validate(email: str) -> tuple[bool, Optional[str]]:
        """
        Validate email and return (is_valid, error_message).
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not email:
            return False, "Email is empty"
        
        if not EmailValidator.is_valid_format(email):
            return False, f"Invalid email format: {email}"
        
        return True, None
