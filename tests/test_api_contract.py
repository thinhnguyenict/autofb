import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
API_FILE = ROOT / "autofb" / "web" / "api.py"
DOCKERFILE = ROOT / "Dockerfile"


def _literal_route_arg(call: ast.Call) -> str | None:
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


class ApiContractTests(unittest.TestCase):
    def test_logout_route_avoids_empty_body_status_codes(self):
        tree = ast.parse(API_FILE.read_text())
        logout_routes = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name != "logout":
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                if _literal_route_arg(decorator) == "/api/v1/auth/logout":
                    logout_routes.append(decorator)

        self.assertEqual(len(logout_routes), 1)
        keywords = {keyword.arg: keyword.value for keyword in logout_routes[0].keywords}
        self.assertNotIn("status_code", keywords)

    def test_api_serves_static_assets_under_api_prefix(self):
        tree = ast.parse(API_FILE.read_text())
        routes = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and _literal_route_arg(decorator) == "/api/v1/static/{asset_path:path}":
                    routes.append(node.name)

        self.assertEqual(routes, ["api_static_asset", "api_static_asset"])
        self.assertEqual(routes, ["api_static_asset"])

    def test_docker_build_imports_runtime_modules(self):
        dockerfile = DOCKERFILE.read_text()

        self.assertIn("python -m compileall -q autofb tools", dockerfile)
        self.assertIn("import autofb.web.api", dockerfile)
        self.assertIn("import autofb.web.worker", dockerfile)


if __name__ == "__main__":
    unittest.main()
