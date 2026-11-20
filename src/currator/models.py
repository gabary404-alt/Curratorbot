"""API types shared by the browser and hardware bridge."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Language = Literal["rw", "en"]
ChatText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1500)]


class ChatTurn(BaseModel):
    role: Literal["user", "model"]
    text: ChatText


class ChatRequest(BaseModel):
    text: ChatText
    language: Language = "rw"
    session_id: str = Field(default="demo", pattern=r"^[\w-]{1,64}$")
    retrieval: Literal["auto", "on", "off"] = "auto"
    history: list[ChatTurn] | None = Field(default=None, max_length=6)


class Source(BaseModel):
    label: str
    url: str


class ChatResponse(BaseModel):
    reply: str
    language: Language
    source_mode: str = "none"
    sources: list[Source] = Field(default_factory=list)
    simulated: bool = False
    audio_url: str | None = None
    audio_error: str | None = None


class TranscriptionResponse(BaseModel):
    text: str
    language: Language
    simulated: bool = False


class RobotCommand(BaseModel):
    action: Literal["stop", "drive", "turn", "auto_step"]
    speed: float = Field(default=0.10, ge=0, le=0.15)
    duration_ms: int = Field(default=400, ge=100, le=750)


class SensorTelemetry(BaseModel):
    front_cm: float = Field(ge=0, le=10000)
    left_cm: float = Field(ge=0, le=10000)
    right_cm: float = Field(ge=0, le=10000)
    bumper_pressed: bool = False
    emergency_stop: bool = False


class RobotResult(BaseModel):
    accepted: bool
    action: str
    transport: str
    simulated: bool
    reason: str = ""
