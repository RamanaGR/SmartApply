#!/usr/bin/env python3
"""SmartApply run entrypoint with safe bootstrap fallback."""

import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _build_fallback_config_loader_module():
    """Provide runtime fallback if src.config_loader has no load_config()."""
    import types

    try:
        import yaml  # type: ignore
    except Exception:
        yaml = None

    class FallbackConfigLoader:
        DEFAULT_CONFIG_PATHS = ["config.yaml", "config.json"]

        def __init__(self, config_file=None):
            self.config_file = config_file
            self.config = {}

        def _defaults(self):
            return {
                "gmail": {
                    "use_api": True,
                    "credentials_path": "credentials.json",
                    "email_delay_min_seconds": 0.5,
                    "email_delay_max_seconds": 1.5,
                    "cooldown_every_n_emails": 10,
                    "cooldown_min_seconds": 30,
                    "cooldown_max_seconds": 60,
                    "rate_limit_per_minute": 60,
                },
                "ollama": {
                    "base_url": "http://localhost:11434",
                    "model": "llama3",
                    "timeout_seconds": 30,
                    "retry_timeout_seconds": 12,
                    "minimal_timeout_seconds": 8,
                    "max_retries": 3,
                    "llm_quality_retries": 3,
                    "retry_backoff_multiplier": 2,
                },
                "input": {
                    "csv_filename": "sample_jobs.csv",
                    "column_mapping": {
                        "email": "Contact Info",
                        "title": "Title",
                        "description": "Description",
                    },
                },
                "email_processing": {
                    "email_limit": None,
                    "daily_cap": 100,
                    "dry_run": False,
                    "test_mode": False,
                    "skip_llm": False,
                    "force_resend": False,
                    "user_confirmation_before_send": True,
                },
                "resume": {
                    "json_path": "resume/Ramana_Gangarao_Resume.json",
                    "pdf_path": "resume/Ramana_Gangarao_Resume.pdf",
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

        def _find_config(self):
            if self.config_file:
                p = Path(self.config_file)
                return p if p.exists() else None
            for name in self.DEFAULT_CONFIG_PATHS:
                p = Path(name)
                if p.exists():
                    return p
            return None

        def _deep_merge(self, base, incoming):
            for k, v in (incoming or {}).items():
                if isinstance(v, dict) and isinstance(base.get(k), dict):
                    self._deep_merge(base[k], v)
                else:
                    base[k] = v

        def load(self):
            cfg = self._defaults()
            config_path = self._find_config()

            if config_path:
                if config_path.suffix.lower() in {".yaml", ".yml"} and yaml is not None:
                    with open(config_path, "r", encoding="utf-8") as f:
                        file_cfg = yaml.safe_load(f) or {}
                    self._deep_merge(cfg, file_cfg)
                elif config_path.suffix.lower() == ".json":
                    with open(config_path, "r", encoding="utf-8") as f:
                        file_cfg = json.load(f)
                    self._deep_merge(cfg, file_cfg)

            env_cred = os.getenv("GMAIL_API_CREDENTIALS_PATH")
            if env_cred:
                cfg.setdefault("gmail", {})["credentials_path"] = env_cred

            self.config = cfg
            return self.config

        def to_dict(self):
            return self.config

    def load_config(config_file=None):
        loader = FallbackConfigLoader(config_file)
        loader.load()
        return loader

    module = types.ModuleType("src.config_loader")
    module.ConfigLoader = FallbackConfigLoader
    module.load_config = load_config
    return module


def _ensure_config_loader():
    """Ensure src.config_loader exposes load_config before importing src.main."""
    try:
        import src.config_loader as cfg_mod  # type: ignore
        if hasattr(cfg_mod, "load_config"):
            return
    except Exception:
        pass

    sys.modules["src.config_loader"] = _build_fallback_config_loader_module()


def main():
    _ensure_config_loader()
    from src.main import main as src_main
    src_main()


if __name__ == "__main__":
    main()
