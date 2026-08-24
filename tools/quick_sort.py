from typing import List


def quick_sort(arr: List[int], left: int = 0, right: int = None) -> List[int]:
    """
    原地快速排序 (In-place Quick Sort)
    
    :param arr: 待排序列表
    :param left: 起始索引 (默认为 0)
    :param right: 结束索引 (默认为列表末尾)
    :return: 排序后的列表 (原数组也会被就地修改)
    """
    if right is None:
        right = len(arr) - 1

    if left < right:
        # 获取分区基准点的最终位置
        pivot_index = partition(arr, left, right)
        # 递归排序左右两部分
        quick_sort(arr, left, pivot_index - 1)
        quick_sort(arr, pivot_index + 1, right)

    return arr


def partition(arr: List[int], left: int, right: int) -> int:
    """
    分区操作：选取最右侧元素为基准 (Pivot)，将小于基准的移到左侧，大于基准的移到右侧
    """
    pivot = arr[right]
    i = left  # 指向小于 pivot 的区域边界

    for j in range(left, right):
        if arr[j] <= pivot:
            arr[i], arr[j] = arr[j], arr[i]
            i += 1

    # 将基准元素放到正确的分界位置
    arr[i], arr[right] = arr[right], arr[i]
    return i


def quick_sort_simple(arr: list) -> list:
    """
    简明快速排序 (通过列表推导式，适合快速理解算法思想)
    """
    if len(arr) <= 1:
        return arr

    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]

    return quick_sort_simple(left) + middle + quick_sort_simple(right)


if __name__ == "__main__":
    # 测试原地快速排序
    test_data = [38, 27, 43, 3, 9, 82, 10]
    print("原始数组:", test_data)
    
    quick_sort(test_data)
    print("原地快排结果:", test_data)

    # 测试简明快速排序
    test_data2 = [5, 2, 9, 1, 5, 6]
    sorted_data = quick_sort_simple(test_data2)
    print("简明快排结果:", sorted_data)
