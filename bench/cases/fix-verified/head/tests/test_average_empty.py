import sys
import unittest

sys.path.insert(0, "src")
from mathx import average


class AverageEmpty(unittest.TestCase):
    def test_empty_list_is_zero(self):
        self.assertEqual(average([]), 0.0)


if __name__ == "__main__":
    unittest.main()
