"""Expected-failure exception types (message text is safe to show to the user)."""

from __future__ import annotations


class JarvisError(Exception):
    """Base class for errors JARVIS can explain instead of crashing."""


class ToolError(JarvisError):
    """A tool refused or failed; the message is handed back to the model."""


class LLMNotConfigured(JarvisError):
    """The active provider has no API key / SDK, so the brain is offline."""


class ConfirmationCancelled(JarvisError):
    """The user did not approve an action in time."""
