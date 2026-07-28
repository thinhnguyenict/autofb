import unittest

from autofb.web.security import http_security_headers


class HttpSecurityHeadersTests(unittest.TestCase):
    def test_api_and_probe_responses_are_not_cached(self):
        for path in ("/api/v1/me", "/healthz", "/readyz", "/workerz", "/backupz"):
            with self.subTest(path=path):
                self.assertEqual(http_security_headers(path)["Cache-Control"], "no-store")

    def test_dashboard_and_static_cache_policies_are_distinct(self):
        self.assertEqual(http_security_headers("/")["Cache-Control"], "no-cache")
        self.assertEqual(http_security_headers("/static/app.js")["Cache-Control"], "public, max-age=3600")

    def test_restrictive_browser_policy_and_opt_in_hsts(self):
        headers = http_security_headers("/")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Permissions-Policy"], "camera=(), microphone=(), geolocation=(), payment=()")
        self.assertNotIn("Strict-Transport-Security", headers)
        self.assertEqual(
            http_security_headers("/", enable_hsts=True)["Strict-Transport-Security"],
            "max-age=31536000; includeSubDomains",
        )

    def test_docs_policy_allows_fastapi_assets_without_weakening_dashboard(self):
        dashboard = http_security_headers("/")["Content-Security-Policy"]
        docs = http_security_headers("/docs")["Content-Security-Policy"]
        self.assertNotIn("unsafe-inline", dashboard)
        self.assertIn("https://cdn.jsdelivr.net", docs)
        self.assertIn("'unsafe-inline'", docs)


if __name__ == "__main__":
    unittest.main()
