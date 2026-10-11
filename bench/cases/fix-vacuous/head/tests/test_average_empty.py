import sys
import unittest

sys.path.insert(0, "src")
from mathx import average


class AverageEmpty(unittest.TestCase):
    def test_basic_mean(self):
        self.assertEqual(average([1, 2, 3]), 2)


if __name__ == "__main__":
    unittest.main()
