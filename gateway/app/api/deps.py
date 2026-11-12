from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.services.pipeline import GatewayPipeline


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_pipeline(request: Request) -> GatewayPipeline:
    pipeline: GatewayPipeline = request.app.state.pipeline
    return pipeline
