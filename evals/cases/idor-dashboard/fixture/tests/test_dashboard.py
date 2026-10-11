import unittest

from app.dashboard import get_dashboard


class DashboardTest(unittest.TestCase):
    def test_owner_can_view_dashboard(self):
        self.assertEqual(get_dashboard("alice", "acct-1")["balance"], 100)

    def test_unknown_account(self):
        with self.assertRaises(KeyError):
            get_dashboard("alice", "acct-404")


if __name__ == "__main__":
    unittest.main()
