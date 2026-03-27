"""Configuration data models."""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class EmailProcessingConfig:
    """Email processing settings."""
    email_limit: Optional[int] = None
    dry_run: bool = False
    user_confirmation_before_send: bool = True


@dataclass
class InputConfig:
    """Input file settings."""
    csv_filename: str
    column_mapping: Dict[str, str] = field(default_factory=dict)


@dataclass
class AppConfig:
    """Application configuration."""
    input: InputConfig
    email_processing: EmailProcessingConfig
    resume_json_path: str
    raw_config: Dict[str, Any] = field(default_factory=dict)
