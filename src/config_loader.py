"""
Configuration loader for SmartApply.
Handles parsing YAML/JSON config files and merging with CLI arguments and environment variables.
"""

import os
import json
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Load and merge configuration from YAML/JSON, CLI args, and environment variables."""

    DEFAULT_CONFIG_PATHS = ["config.yaml", "config.json"]

    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize ConfigLoader.
        
        Args:
            config_file: Path to config file (YAML or JSON). If None, searches DEFAULT_CONFIG_PATHS.
        """
        self.config_file = config_file
        self.config = {}

    def load(self) -> Dict[str, Any]:
        """
        Load configuration from file, environment variables, and CLI overrides.
        
        Returns:
            Merged configuration dictionary.
        """
        # Load from file
        config_path = self._find_config_file()
        if config_path:
            logger.info(f"Loading configuration from {config_path}")
            self.config = self._load_config_file(config_path)
        else:
            logger.warning("No config file found. Using defaults.")
            self.config = self._load_default_config()

        # Merge environment variables
        self._merge_env_vars()

        # Validate configuration
        self._validate_config()

        return self.config

    def _find_config_file(self) -> Optional[Path]:
        """Find config file from provided path or search defaults."""
        if self.config_file:
            path = Path(self.config_file)
            if path.exists():
                return path
            else:
                raise FileNotFoundError(f"Config file not found: {self.config_file}")

        for config_name in self.DEFAULT_CONFIG_PATHS:
            path = Path(config_name)
            if path.exists():
                return path

        return None

    def _load_config_file(self, config_path: Path) -> Dict[str, Any]:
        """Load configuration from YAML or JSON file."""
        try:
            if config_path.suffix.lower() == ".yaml" or config_path.suffix.lower() == ".yml":
                with open(config_path, "r") as f:
                    return yaml.safe_load(f) or {}
            elif config_path.suffix.lower() == ".json":
                with open(config_path, "r") as f:
                    return json.load(f)
            else:
                raise ValueError(f"Unsupported config file format: {config_path.suffix}")
        except Exception as e:
            logger.error(f"Failed to load config from {config_path}: {e}")
            raise

    def _load_default_config(self) -> Dict[str, Any]:
        """Return default configuration."""
        return {
            "gmail": {
                "use_api": False,
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "email_delay_seconds": 0.5,
                "rate_limit_per_minute": 60,
            },
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "llama3",
                "timeout_seconds": 30,
                "max_retries": 3,
                "retry_backoff_multiplier": 2,
            },
            "email_processing": {
                "email_limit": None,
                "dry_run": False,
                "test_mode": False,
                "skip_llm": False,
                "force_resend": False,
                "column_mapping": {},
            },
            "resume": {
                "json_path": "resume/resume.json",
                "pdf_path": "resume/resume.pdf",
            },
            "file_paths": {
                "input_dir": "input",
                "output_dir": "logs",
                "sent_emails_db": "data/sent_emails.json",
                "app_log": "logs/app.log",
                "error_log": "logs/error.log",
            },
            "logging": {
                "level": "INFO",
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        }

    def _merge_env_vars(self):
        """Override config with environment variables."""
        env_overrides = {
            "GMAIL_ADDRESS": ("gmail", "address"),
            "GMAIL_APP_PASSWORD": ("gmail", "app_password"),
            "GMAIL_API_CREDENTIALS_PATH": ("gmail", "api_credentials_path"),
            "OLLAMA_BASE_URL": ("ollama", "base_url"),
            "OLLAMA_MODEL": ("ollama", "model"),
            "INPUT_DIR": ("file_paths", "input_dir"),
            "RESUME_JSON": ("resume", "json_path"),
            "RESUME_PDF": ("resume", "pdf_path"),
        }

        for env_key, (section, key) in env_overrides.items():
            if env_value := os.getenv(env_key):
                if section not in self.config:
                    self.config[section] = {}
                self.config[section][key] = env_value
                logger.debug(f"Override from env: {env_key} -> {section}.{key}")

    def _validate_config(self):
        """Validate configuration structure and required fields."""
        required_sections = ["gmail", "ollama", "email_processing", "resume", "file_paths", "logging"]
        for section in required_sections:
            if section not in self.config:
                logger.warning(f"Missing config section: {section}. Using defaults.")
                self.config[section] = self._load_default_config().get(section, {})

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        Get config value by nested keys.
        
        Example:
            config.get("gmail", "smtp_host") -> "smtp.gmail.com"
        """
        value = self.config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
        return value if value is not None else default

    def set(self, *keys: str, value: Any):
        """
        Set config value by nested keys.
        
        Example:
            config.set("gmail", "smtp_host", value="smtp.gmail.com")
        """
        config_ref = self.config
        for key in keys[:-1]:
            if key not in config_ref:
                config_ref[key] = {}
            config_ref = config_ref[key]
        config_ref[keys[-1]] = value

    def to_dict(self) -> Dict[str, Any]:
        """Return config as dictionary."""
        return self.config


def load_config(config_file: Optional[str] = None) -> ConfigLoader:
    """Convenience function to load config."""
    loader = ConfigLoader(config_file)
    loader.load()
    return loader
