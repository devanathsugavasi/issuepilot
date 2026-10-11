import unittest

from shop.pricing import apply_discount


class PricingTest(unittest.TestCase):
    def test_ten_percent(self):
        self.assertEqual(apply_discount(1000, 10), 900)

    def test_no_discount(self):
        self.assertEqual(apply_discount(1000, 0), 1000)

    def test_rejects_invalid_percent(self):
        with self.assertRaises(ValueError):
            apply_discount(1000, 150)


if __name__ == "__main__":
    unittest.main()
