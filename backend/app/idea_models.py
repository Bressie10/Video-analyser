"""Strict API/model contracts for one generated idea."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GeneratedIdea(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=300)
    concept: str = Field(min_length=1, max_length=10000)
    script: str = Field(min_length=1, max_length=30000)

    @field_validator('title', 'concept', 'script')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank.')
        return value


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    video_ids: list[UUID] = Field(min_length=1, max_length=20)
    generation_brief: str | None = Field(default=None, max_length=10000)
    target_platforms: list[Literal['instagram', 'facebook']] = Field(min_length=1, max_length=2)
    history_limit: int = Field(default=20, ge=0, le=20)

    @field_validator('video_ids', 'target_platforms')
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('Duplicate selections are not allowed.')
        return value


class IdeaEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None, min_length=1, max_length=300)
    concept: str | None = Field(default=None, min_length=1, max_length=10000)
    script: str | None = Field(default=None, min_length=1, max_length=30000)
    status: Literal['draft', 'used', 'published', 'discarded'] | None = None

    @model_validator(mode='after')
    def valid_edit(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None or not getattr(self, key).strip()
            for key in self.model_fields_set
        ):
            raise ValueError('Supply at least one nonblank title, concept, script or valid status.')
        return self


class IdeaFeedback(BaseModel):
    model_config = ConfigDict(extra='forbid')
    feedback: Literal['none', 'liked', 'disliked']
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode='after')
    def valid_reason(self):
        if self.reason is not None:
            self.reason = self.reason.strip() or None
        if self.feedback != 'disliked' and self.reason is not None:
            raise ValueError('A reason is supported only for disliked feedback.')
        return self
