"""Domain errors. The API layer maps these to HTTP status codes in one place."""


class FolioError(Exception):
    """Base class for expected, user-presentable errors."""


class NotFound(FolioError):
    pass


class Conflict(FolioError):
    """The request is valid but conflicts with current state (e.g. undo after later edits)."""


class InvalidInput(FolioError):
    pass


class PrivacyBlocked(FolioError):
    """A component tried to use a non-local provider without the project's opt-in."""


class Unavailable(FolioError):
    """An optional capability (microphone, speech model, ...) is not installed or configured."""
