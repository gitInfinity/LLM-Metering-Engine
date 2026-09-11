import logging
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from src.core.errors import register_error_handlers
from src.core.errors import AuthenticationError, MeteringError, PricingUnavailable
from src.core.logging import configure_logging


class ErrorHandlingTests(unittest.TestCase):
    def test_shared_logging_levels_and_exception(self):
        from src.core import logging as app_logging

        with self.assertLogs("capstone", level="DEBUG") as captured:
            for level in ("debug", "info", "warning", "error", "critical"):
                getattr(app_logging, level)(__name__, "event=%s", level)
            try:
                raise ValueError("safe test exception")
            except ValueError:
                app_logging.exception(__name__, "Test failure")
        self.assertEqual([record.levelname for record in captured.records],
                         ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "ERROR"])
        self.assertEqual(captured.records[0].getMessage(), "event=debug")
        self.assertEqual(captured.records[0].funcName, "test_shared_logging_levels_and_exception")
        self.assertIsNotNone(captured.records[-1].exc_info)

    def test_logging_configuration_is_repeatable(self):
        configure_logging()
        logger = logging.getLogger("capstone")
        handlers = list(logger.handlers)
        configure_logging()
        self.assertEqual(logger.handlers, handlers)
        self.assertFalse(logger.propagate)

    def test_statuses_and_secret_redaction(self):
        app = FastAPI()
        register_error_handlers(app)
        errors = {
            "auth": AuthenticationError("Invalid or expired API key."),
            "quota": MeteringError(429, "Quota exceeded."),
            "pricing": PricingUnavailable("Server pricing is missing or invalid."),
            "database": OperationalError("secret-sql", {"key": "secret-key"}, Exception("secret-password")),
            "unexpected": RuntimeError("secret-prompt"),
        }

        @app.get("/error/{kind}")
        def fail(kind: str):
            raise errors[kind]

        with TestClient(app, raise_server_exceptions=False) as client:
            with self.assertLogs("capstone", level="INFO") as logs:
                for kind, status in (("auth", 401), ("quota", 429), ("pricing", 503),
                                     ("database", 503), ("unexpected", 500)):
                    response = client.get(f"/error/{kind}")
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(response.json()["error_code"], status)
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertNotIn("secret-", response.text)
                    if kind == "auth":
                        self.assertEqual(response.headers["www-authenticate"], "Bearer")
            self.assertNotIn("secret-", " ".join(logs.output))
