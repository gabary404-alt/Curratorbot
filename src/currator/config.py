"""Centralized configuration. No secrets in source control."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    mode: str = os.getenv("CURRATOR_MODE", "mock").lower()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    google_search_grounding: bool = os.getenv("GOOGLE_SEARCH_GROUNDING", "false").lower() == "true"
    vosk_model_path: str = os.getenv("VOSK_MODEL_PATH", "")
    pindo_token: str = os.getenv("PINDO_API_TOKEN", "")
    pindo_media_base_url: str = os.getenv("PINDO_MEDIA_BASE_URL", "")
    wikimedia_user_agent: str = os.getenv(
        "WIKIMEDIA_USER_AGENT", "CurratorBot/0.1 (contact: support@example.com)"
    )
    enable_motion: bool = os.getenv("ENABLE_MOTION", "false").lower() == "true"
    robot_transport: str = os.getenv("ROBOT_TRANSPORT", "mock").lower()
    robot_serial_port: str = os.getenv("ROBOT_SERIAL_PORT", "")
    robot_serial_baud: int = int(os.getenv("ROBOT_SERIAL_BAUD", "115200"))
    robot_operator_token: str = os.getenv("ROBOT_OPERATOR_TOKEN", "")

    def validate(self) -> None:
        if self.mode not in {"mock", "rehearsal", "live"}:
            raise ValueError("CURRATOR_MODE must be 'mock', 'rehearsal' or 'live'")
        if self.robot_transport not in {"mock", "serial"}:
            raise ValueError("ROBOT_TRANSPORT must be 'mock' or 'serial'")
        if self.mode == "live" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY required in live mode")
        if self.enable_motion and (
            not self.robot_operator_token or len(self.robot_operator_token) < 24
        ):
            raise ValueError("Motion requires a random ROBOT_OPERATOR_TOKEN of at least 24 characters")
        if self.robot_transport == "serial" and not self.robot_serial_port:
            raise ValueError("ROBOT_SERIAL_PORT required for serial transport")
