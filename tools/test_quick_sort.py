import random
import unittest
from quick_sort import quick_sort, quick_sort_simple


class TestQuickSort(unittest.TestCase):
    """快速排序单元测试"""

    def setUp(self):
        # 常见测试用例集合
        self.test_cases = [
            [],                             # 空数组
            [42],                           # 单元素
            [1, 2, 3, 4, 5],                # 已升序
            [5, 4, 3, 2, 1],                # 逆序
            [3, 1, 4, 1, 5, 9, 2, 6, 5],    # 包含重复元素
            [8, 8, 8, 8, 8],                # 全相同元素
            [-10, 0, 5, -2, 100, -50],      # 包含负数与0
        ]

    def test_quick_sort_in_place(self):
        """测试原地快速排序 (quick_sort)"""
        for arr in self.test_cases:
            with self.subTest(case="basic", input=arr):
                data = list(arr)
                expected = sorted(arr)
                result = quick_sort(data)
                # 检查返回值与就地修改后的数组
                self.assertEqual(result, expected)
                self.assertEqual(data, expected)

    def test_quick_sort_simple(self):
        """测试简明快速排序 (quick_sort_simple)"""
        for arr in self.test_cases:
            with self.subTest(case="basic", input=arr):
                data = list(arr)
                expected = sorted(arr)
                result = quick_sort_simple(data)
                self.assertEqual(result, expected)

    def test_random_large_arrays(self):
        """随机生成较大规模数组进行压力测试"""
        for size in [50, 200, 1000]:
            random_arr = [random.randint(-10000, 10000) for _ in range(size)]
            expected = sorted(random_arr)

            with self.subTest(case="random", size=size):
                # 测试原地快排
                data1 = list(random_arr)
                self.assertEqual(quick_sort(data1), expected)

                # 测试简明快排
                data2 = list(random_arr)
                self.assertEqual(quick_sort_simple(data2), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
