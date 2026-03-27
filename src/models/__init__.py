"""Data models for SmartApply."""

from src.models.email import Email, EmailValidationResult
from src.models.csv_row import CSVRow
from src.models.resume import Resume, ResumeData
from src.models.config import EmailProcessingConfig, InputConfig, AppConfig

__all__ = [
    "Email",
    "EmailValidationResult",
    "CSVRow",
    "Resume",
    "ResumeData",
    "EmailProcessingConfig",
    "InputConfig",
    "AppConfig",
]
