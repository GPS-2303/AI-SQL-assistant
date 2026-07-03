import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main


class ApiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._cfg_backup = dict(main.cfg)
        self._startup_patcher = patch("backend.app.main.ensure_audit_table", return_value=None)
        self._startup_patcher.start()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.cfg.clear()
        main.cfg.update(self._cfg_backup)
        self._startup_patcher.stop()

    def test_health_is_public(self):
        main.cfg["api_key"] = "test-key"
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_query_requires_api_key_when_enabled(self):
        main.cfg["api_key"] = "test-key"
        response = self.client.post("/query", json={"question": "show customers", "explain": False})
        self.assertEqual(response.status_code, 401)

    def test_query_with_api_key_succeeds(self):
        main.cfg["api_key"] = "test-key"
        with (
            patch("backend.app.main.build_prompt", return_value="prompt"),
            patch("backend.app.main.call_ollama", return_value="SELECT * FROM customers"),
            patch("backend.app.main.clean_sql", return_value="SELECT * FROM customers"),
            patch("backend.app.main.validate_and_normalize_sql", return_value="SELECT * FROM customers LIMIT 50"),
            patch("backend.app.main.statement_kind", return_value="select"),
        ):
            response = self.client.post(
                "/query",
                json={"question": "show customers", "explain": False},
                headers={"X-API-Key": "test-key"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["statement_kind"], "select")
        self.assertFalse(response.json()["requires_confirmation"])

    def test_execute_write_requires_confirm(self):
        main.cfg["api_key"] = "test-key"
        with (
            patch("backend.app.main.validate_and_normalize_sql", return_value="UPDATE customers SET country='US' WHERE id=1"),
            patch("backend.app.main.statement_kind", return_value="update"),
            patch("backend.app.main.safe_write_audit_log", return_value=None),
        ):
            response = self.client.post(
                "/execute",
                json={"sql": "UPDATE customers SET country='US' WHERE id=1"},
                headers={"X-API-Key": "test-key"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("confirm='YES'", response.json()["detail"])

    def test_execute_write_with_confirm_succeeds(self):
        main.cfg["api_key"] = "test-key"
        main.cfg["allow_full_table_write"] = False
        main.cfg["max_write_rows"] = 100
        with (
            patch("backend.app.main.validate_and_normalize_sql", return_value="UPDATE customers SET country='US' WHERE id=1"),
            patch("backend.app.main.statement_kind", return_value="update"),
            patch("backend.app.main.has_where_clause", return_value=True),
            patch("backend.app.main.estimate_affected_rows", return_value=1),
            patch("backend.app.main.run_sql", return_value=([], [], 1)),
            patch("backend.app.main.safe_write_audit_log", return_value=None),
        ):
            response = self.client.post(
                "/execute",
                json={"sql": "UPDATE customers SET country='US' WHERE id=1", "confirm": "YES"},
                headers={"X-API-Key": "test-key"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["affected_rows"], 1)

    def test_audit_requires_api_key_when_enabled(self):
        main.cfg["api_key"] = "test-key"
        response = self.client.get("/audit?limit=5")
        self.assertEqual(response.status_code, 401)

    def test_audit_with_api_key_succeeds(self):
        main.cfg["api_key"] = "test-key"
        with patch(
            "backend.app.main.run_sql",
            return_value=(["id", "status"], [{"id": 1, "status": "executed"}], 1),
        ):
            response = self.client.get("/audit?limit=5", headers={"X-API-Key": "test-key"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["rows"]), 1)

    def test_schema_returns_schema_sql(self):
        main.cfg["api_key"] = "test-key"
        response = self.client.get("/schema", headers={"X-API-Key": "test-key"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("schema_sql", response.json())
        self.assertIn("database", response.json())

    def test_ask_auto_executes_select(self):
        main.cfg["api_key"] = "test-key"
        with (
            patch("backend.app.main.build_prompt", return_value="prompt"),
            patch("backend.app.main.call_ollama", return_value="SELECT * FROM customers"),
            patch("backend.app.main.clean_sql", return_value="SELECT * FROM customers"),
            patch("backend.app.main.validate_and_normalize_sql", return_value="SELECT * FROM customers LIMIT 50"),
            patch("backend.app.main.statement_kind", return_value="select"),
            patch(
                "backend.app.main.run_sql",
                return_value=(["id"], [{"id": 1}], 1),
            ),
            patch("backend.app.main.safe_write_audit_log", return_value=None),
        ):
            response = self.client.post(
                "/ask",
                json={"question": "show customers", "explain": False},
                headers={"X-API-Key": "test-key"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["statement_kind"], "select")
        self.assertEqual(response.json()["rows"], [{"id": 1}])

    def test_ask_rejects_write_statements(self):
        main.cfg["api_key"] = "test-key"
        with (
            patch("backend.app.main.build_prompt", return_value="prompt"),
            patch("backend.app.main.call_ollama", return_value="UPDATE customers SET country='US' WHERE id=1"),
            patch("backend.app.main.clean_sql", return_value="UPDATE customers SET country='US' WHERE id=1"),
            patch(
                "backend.app.main.validate_and_normalize_sql",
                return_value="UPDATE customers SET country='US' WHERE id=1",
            ),
            patch("backend.app.main.statement_kind", return_value="update"),
        ):
            response = self.client.post(
                "/ask",
                json={"question": "set customer 1 to US", "explain": False},
                headers={"X-API-Key": "test-key"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("requires confirmation", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
