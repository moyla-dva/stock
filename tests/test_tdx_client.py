import unittest
from unittest.mock import patch

from stock_analyzer.providers import tdx_client


class TdxClientTest(unittest.TestCase):
    def test_call_resolves_method_again_after_reconnect(self):
        class BrokenApi:
            def get_security_bars(self, *args):
                raise ConnectionError("connection dropped")

        class ReconnectedApi:
            def get_security_bars(self, *args):
                return [{"datetime": "2026-09-24", "close": 10.0}]

        with patch.object(
            tdx_client,
            "_connect",
            side_effect=[BrokenApi(), ReconnectedApi()],
        ) as connect, patch.object(tdx_client, "_reset") as reset:
            result = tdx_client._call("get_security_bars", 9, 1, "600063", 0, 700, retries=1)

        self.assertEqual(result[0]["close"], 10.0)
        self.assertEqual(connect.call_count, 2)
        reset.assert_called_once_with()

    def test_call_does_not_reconnect_after_final_failure(self):
        class BrokenApi:
            def get_security_bars(self, *args):
                raise RuntimeError("still broken")

        with patch.object(tdx_client, "_connect", return_value=BrokenApi()) as connect, patch.object(
            tdx_client,
            "_reset",
        ) as reset:
            with self.assertRaisesRegex(RuntimeError, "still broken"):
                tdx_client._call("get_security_bars", 9, 1, "600063", 0, 700, retries=1)

        self.assertEqual(connect.call_count, 2)
        reset.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
