"""Small, provider-agnostic error types with friendly messages."""


class ProviderError(Exception):
    """A free scholarly API failed. The message is safe to show to a student."""

    def __init__(self, provider: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.message = message
        self.status = status

    def friendly(self) -> str:
        if self.status == 429:
            return f"{self.provider} is rate-limiting us. Results from other sources are still shown."
        if self.status is not None and self.status >= 500:
            return f"{self.provider} is temporarily unavailable. Results from other sources are still shown."
        return f"{self.provider} could not be reached ({self.message}). Results from other sources are still shown."
