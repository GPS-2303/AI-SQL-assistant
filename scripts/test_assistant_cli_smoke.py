import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import sql_service


class AssistantCliSafetyTests(unittest.TestCase):
    def test_extract_first_statement_skips_prefix_text(self):
        sql = "Here is the query:\nSELECT id, email FROM customers;"
        out = sql_service.extract_first_statement(sql)
        self.assertEqual(out, "SELECT id, email FROM customers;")

    def test_validate_select_adds_limit(self):
        sql = "SELECT * FROM customers"
        out = sql_service.validate_and_normalize_sql(sql)
        self.assertEqual(out, "SELECT * FROM customers LIMIT 50")

    def test_validate_select_keeps_existing_limit(self):
        sql = "SELECT * FROM customers LIMIT 10"
        out = sql_service.validate_and_normalize_sql(sql)
        self.assertEqual(out, "SELECT * FROM customers LIMIT 10")

    def test_validate_update_is_allowed(self):
        sql = "UPDATE customers SET email = 'x@example.com' WHERE id = 1;"
        out = sql_service.validate_and_normalize_sql(sql)
        self.assertEqual(out, "UPDATE customers SET email = 'x@example.com' WHERE id = 1")

    def test_multiple_statements_are_blocked(self):
        with self.assertRaises(ValueError):
            sql_service.validate_and_normalize_sql("SELECT * FROM customers; DELETE FROM customers;")

    def test_statement_kind_detection(self):
        kind = sql_service.statement_kind("  delete from customers where id = 2")
        self.assertEqual(kind, "delete")

    def test_has_where_clause(self):
        self.assertTrue(sql_service.has_where_clause("UPDATE customers SET country='US' WHERE id=1"))
        self.assertFalse(sql_service.has_where_clause("DELETE FROM customers"))


if __name__ == "__main__":
    unittest.main()
