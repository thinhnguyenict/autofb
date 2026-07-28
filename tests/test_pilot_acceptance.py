import io
import json
import unittest

from tools.pilot_acceptance import PilotAcceptanceError, pilot_acceptance, validate_base_url


class Response:
    def __init__(self, status, payload):
        self.status = status
        self.body = io.BytesIO(json.dumps(payload).encode())

    def read(self, size=-1):
        return self.body.read(size)

    def close(self):
        self.body.close()


class PilotAcceptanceTests(unittest.TestCase):
    def test_all_required_public_gates_pass(self):
        statuses = {
            "/healthz": "ok",
            "/readyz": "ready",
            "/workerz": "ready",
            "/backupz": "ready",
        }
        requested = []

        def opener(request, *, timeout):
            requested.append((request.full_url, timeout))
            path = "/" + request.full_url.rsplit("/", 1)[-1]
            return Response(200, {"status": statuses[path]})

        report = pilot_acceptance("https://autofb.example", opener=opener)

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["failed_checks"], [])
        self.assertEqual(len(requested), 4)
        self.assertTrue(all(timeout == 5 for _, timeout in requested))

    def test_failed_or_invalid_probe_is_reported_without_response_body(self):
        def opener(request, *, timeout):
            if request.full_url.endswith("/workerz"):
                return Response(503, {"status": "not_ready", "secret": "must-not-leak"})
            if request.full_url.endswith("/backupz"):
                return Response(200, {"status": "unexpected", "secret": "must-not-leak"})
            expected = "ok" if request.full_url.endswith("/healthz") else "ready"
            return Response(200, {"status": expected})

        report = pilot_acceptance("https://autofb.example", opener=opener)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failed_checks"], ["/backupz", "/workerz"])
        self.assertNotIn("must-not-leak", str(report))

    def test_public_url_rejects_http_credentials_paths_and_queries(self):
        invalid = (
            "http://autofb.example",
            "https://localhost:8001",
            "https://token@autofb.example",
            "https://autofb.example/app",
            "https://autofb.example?token=secret",
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(PilotAcceptanceError):
                    validate_base_url(value)
        self.assertEqual(
            validate_base_url("http://127.0.0.1:8001", allow_insecure_http=True),
            "http://127.0.0.1:8001",
        )


if __name__ == "__main__":
    unittest.main()
