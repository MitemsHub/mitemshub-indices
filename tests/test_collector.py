from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from synthetic_trader.config import DEFAULT_DERIV_APP_ID
from synthetic_trader.data.collector import collect_history, deriv_credentials_from_env


class CollectorTests(unittest.TestCase):
    def test_uses_default_app_id(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            credentials = deriv_credentials_from_env()

        self.assertEqual(credentials.app_id, DEFAULT_DERIV_APP_ID)
        self.assertIsNone(credentials.token)

    def test_explicit_app_id_overrides_default(self) -> None:
        credentials = deriv_credentials_from_env(app_id="123")

        self.assertEqual(credentials.app_id, "123")

    def test_collect_history_rejects_invalid_count(self) -> None:
        with self.assertRaises(ValueError):
            import asyncio

            asyncio.run(collect_history("R_75", 0, "ignored.csv"))


if __name__ == "__main__":
    unittest.main()
