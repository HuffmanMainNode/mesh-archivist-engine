"""Agent-facing protocol primitives for Mesh Archivist Engine."""
from .protocol import PROTOCOL, build_result, capability_manifest, validate_task
__all__ = ["PROTOCOL", "build_result", "capability_manifest", "validate_task"]
