"""Resume data loading and handling."""

import json
import logging
from pathlib import Path
from typing import Optional

from src.models.resume import Resume, ResumeData

logger = logging.getLogger(__name__)


class ResumeHandler:
    """Handle resume data loading and extraction."""
    
    @staticmethod
    def load_resume(json_path: str) -> Resume:
        """
        Load resume from JSON file.
        
        Args:
            json_path: Path to resume.json
            
        Returns:
            Resume object with data if loaded, empty if failed
        """
        resume_path = Path(json_path)
        resume = Resume(json_path=json_path)
        
        if not resume_path.exists():
            logger.warning(f"Resume file not found: {json_path}")
            return resume
        
        try:
            with open(resume_path, "r") as f:
                raw_data = json.load(f)
            
            name = ResumeHandler._extract_name(raw_data)
            skills = ResumeHandler._extract_skills(raw_data)
            
            resume.data = ResumeData(
                name=name,
                skills=skills,
                raw_data=raw_data
            )
            
            logger.info(f"Loaded resume: {json_path} (Name: {name})")
            return resume
            
        except Exception as e:
            logger.error(f"Failed to load resume: {e}")
            return resume
    
    @staticmethod
    def _extract_name(resume_data: dict) -> str:
        """Extract candidate name from resume."""
        try:
            name = resume_data.get("cv", {}).get("name", "")
            if name:
                return name
        except Exception as e:
            logger.debug(f"Failed to extract name: {e}")
        
        return "Applicant"
    
    @staticmethod
    def _extract_skills(resume_data: dict) -> list[str]:
        """Extract skills list from resume."""
        try:
            skills = resume_data.get("skills", [])
            if isinstance(skills, list):
                return skills
        except Exception as e:
            logger.debug(f"Failed to extract skills: {e}")
        
        return []
