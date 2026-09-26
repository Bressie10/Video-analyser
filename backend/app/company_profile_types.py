"""Versioned profile documents and centralized cost/worker policy."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Scope = Literal['shared', 'instagram', 'facebook', 'meta_ads']
SCOPES = ('shared', 'instagram', 'facebook', 'meta_ads')
PLATFORMS = SCOPES[1:]
GENERATOR_VERSION = '1'
SCHEMA_VERSION = '1'
MAX_ITEMS = 40
MAX_PERFORMANCES = 80
MAX_TRANSCRIPT_CHARS = 2000
MAX_SCENES = 12
MAX_OCR = 20
MAX_MOTION = 12
MAX_TEXT_CHARS = 500
MAX_INPUT_BYTES = 24 * 1024
MAX_OUTPUT_BYTES = 24 * 1024
MAX_OUTPUT_TOKENS = 3000
MAX_CLAIMS = 12
MAX_LIMITATIONS = 20
INPUT_RESERVE_BYTES = 256
MAX_RELATIONSHIPS = MAX_ITEMS * MAX_PERFORMANCES
MODEL_TIMEOUT_SECONDS = 60
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 20
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 30
POLL_SECONDS = 2
WORKER_LOCK = 72419400
VERSION_SCAN_LIMIT = 100


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Claim(StrictModel):
    text: str = Field(max_length=MAX_TEXT_CHARS)
    evidence_refs: list[str] = Field(max_length=MAX_ITEMS + MAX_PERFORMANCES)
    comparison_basis: str = Field(max_length=MAX_TEXT_CHARS)
    evidence_kind: Literal['content', 'measured_performance', 'user_preference']
    confidence: Literal['low', 'medium', 'high']
    supporting_count: int = Field(default=0, ge=0)


class ProfileDocument(StrictModel):
    topics: list[Claim] = Field(default_factory=list, max_length=MAX_CLAIMS)
    tone_style: list[Claim] = Field(default_factory=list, max_length=MAX_CLAIMS)
    recurring_patterns: list[Claim] = Field(default_factory=list, max_length=MAX_CLAIMS)
    strong_themes: list[Claim] = Field(default_factory=list, max_length=MAX_CLAIMS)
    weak_themes: list[Claim] = Field(default_factory=list, max_length=MAX_CLAIMS)
    repetition_signals: list[Claim] = Field(default_factory=list, max_length=MAX_CLAIMS)
    cross_platform_observations: list[Claim] = Field(default_factory=list, max_length=MAX_CLAIMS)
    user_preferences: list[Claim] = Field(default_factory=list, max_length=MAX_CLAIMS)
    limitations: list[str] = Field(default_factory=list, max_length=MAX_LIMITATIONS)
    confidence: Literal['insufficient', 'low', 'medium', 'high'] = 'insufficient'
    coverage: dict = Field(default_factory=dict)
