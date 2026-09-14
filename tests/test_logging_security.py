import logging

from sut_control_center.logging_config import RedactingFormatter


def test_secrets_and_sensitive_headers_are_redacted():
    secrets = ("telegram-secret", "ozon-api-secret", "ozon-client-id")
    formatter = RedactingFormatter("%(message)s", secrets)
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "token=%s Authorization: Bearer exposed Cookie=session Password=hunter2 client=%s", ("telegram-secret", "ozon-client-id"), None)
    output = formatter.format(record)
    assert all(secret not in output for secret in secrets)
    assert "exposed" not in output and "session" not in output and "hunter2" not in output
    assert "[REDACTED]" in output
