class OzonAPIError(RuntimeError):
    """Base safe-to-log Ozon API error."""


class OzonAuthError(OzonAPIError):
    """Ozon rejected the supplied credentials."""


class OzonHTTPError(OzonAPIError):
    """Ozon returned an unsuccessful HTTP status."""


class OzonNetworkError(OzonAPIError):
    """Ozon could not be reached within the configured limits."""


class OzonResponseError(OzonAPIError):
    """Ozon returned a response that could not be decoded."""
