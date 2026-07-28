import json
import logging
import unittest

from autofb.web.observability import (
    ErrorReportLimiter,
    JsonFormatter,
    configure_logging,
    report_unhandled_error,
    request_id,
)


class ObservabilityTests(unittest.TestCase):
    def test_request_id_accepts_safe_value_and_replaces_unsafe_input(self):
        self.assertEqual(request_id("campaign-42"), "campaign-42")
        generated = request_id("bad id\nforged-log")
        self.assertNotIn("\n", generated)
        self.assertEqual(len(generated), 36)

    def test_json_formatter_emits_metadata_without_arbitrary_record_fields(self):
        record = logging.LogRecord("autofb.api", logging.ERROR, __file__, 1, "request failed", (), None)
        record.request_id = "req-1"
        record.method = "POST"
        record.path = "/api/v1/posts"
        record.access_token = "must-not-leak"
        payload = json.loads(JsonFormatter().format(record))
        self.assertEqual(payload["event"], "request failed")
        self.assertEqual(payload["request_id"], "req-1")
        self.assertEqual(payload["path"], "/api/v1/posts")
        self.assertNotIn("access_token", payload)

    def test_logging_configuration_is_idempotent(self):
        logger = configure_logging("autofb.test-observability")
        configure_logging("autofb.test-observability")
        self.addCleanup(logger.handlers.clear)
        self.assertEqual(sum(getattr(item, "_autofb_json", False) for item in logger.handlers), 1)

    def test_error_report_contains_only_allowlisted_fields(self):
        captured = {}

        class Response:
            status_code = 202

        def sender(url, *, json, headers, timeout):
            captured.update(url=url, payload=json, headers=headers, timeout=timeout)
            return Response()

        delivered = report_unhandled_error(
            "https://errors.example/events",
            request_id_value="request-1",
            method="POST",
            path="/api/v1/posts",
            error_type="RuntimeError",
            bearer_token="reporting-secret",
            sender=sender,
        )

        self.assertTrue(delivered)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer reporting-secret")
        self.assertEqual(captured["timeout"], 3)
        self.assertEqual(
            set(captured["payload"]),
            {"service", "event", "request_id", "method", "path", "error_type", "occurred_at"},
        )
        self.assertNotIn("reporting-secret", str(captured["payload"]))

    def test_error_report_rejects_insecure_webhook_and_http_failure(self):
        self.assertFalse(
            report_unhandled_error(
                "http://errors.example/events",
                request_id_value="request-1",
                method="GET",
                path="/",
                error_type="RuntimeError",
                sender=lambda *args, **kwargs: self.fail("insecure webhook must not be called"),
            )
        )

        class Response:
            status_code = 503

        self.assertFalse(
            report_unhandled_error(
                "https://errors.example/events",
                request_id_value="request-1",
                method="GET",
                path="/",
                error_type="RuntimeError",
                sender=lambda *args, **kwargs: Response(),
            )
        )

    def test_error_report_limiter_suppresses_duplicates_until_cooldown(self):
        timestamps = iter((100.0, 101.0, 161.0))
        limiter = ErrorReportLimiter(cooldown_seconds=60, clock=lambda: next(timestamps))
        self.assertTrue(limiter.allow("GET", "/readyz", "RuntimeError"))
        self.assertFalse(limiter.allow("GET", "/readyz", "RuntimeError"))
        self.assertTrue(limiter.allow("GET", "/readyz", "RuntimeError"))

    def test_error_report_limiter_bounds_fingerprint_memory(self):
        limiter = ErrorReportLimiter(cooldown_seconds=60, max_fingerprints=2, clock=lambda: 100.0)
        self.assertTrue(limiter.allow("GET", "/one", "RuntimeError"))
        self.assertTrue(limiter.allow("GET", "/two", "RuntimeError"))
        self.assertTrue(limiter.allow("GET", "/three", "RuntimeError"))
        self.assertTrue(limiter.allow("GET", "/one", "RuntimeError"))


if __name__ == "__main__":
    unittest.main()
