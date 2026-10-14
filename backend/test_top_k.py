import random

import pytest

from top_k import MinHeap, top_k

def heap_is_valid(heap: MinHeap) -> bool:

    items, key = heap._items, heap._key
    return all(key(items[(i - 1) // 2]) <= key(items[i]) for i in range(1, len(items)))


# ------------- MinHeap

def test_pop_returns_items_in_ascending_order():
    rng = random.Random(1)
    values = [rng.randint(-1000, 1000) for _ in range(500)]
    heap = MinHeap()
    for v in values:
        heap.push(v)
        assert heap_is_valid(heap)
    popped = [heap.pop() for _ in range(len(values))]
    assert popped == sorted(values)
    assert heap.is_empty()


def test_peek_does_not_remove():
    heap = MinHeap()
    for v in (5, 3, 8):
        heap.push(v)
    assert heap.peek() == 3
    assert len(heap) == 3

def test_empty_heap_raises():
    heap = MinHeap()
    with pytest.raises(IndexError):
        heap.pop()
    with pytest.raises(IndexError):
        heap.peek()

def test_key_function_orders_dicts():
    heap = MinHeap(key=lambda r: r["trips"])
    for trips in (40, 10, 30):
        heap.push({"trips": trips})
    assert [heap.pop()["trips"] for _ in range(3)] == [10, 30, 40]



# ----------------- top_k

def test_basic_example():
    routes = [{"id": "a", "trips": 50}, {"id": "b", "trips": 500},
              {"id": "c", "trips": 20}, {"id": "d", "trips": 350}]
    result = top_k(routes, 2, key=lambda r: r["trips"])
    assert [r["id"] for r in result] == ["b", "d"]

@pytest.mark.parametrize("k", [0. -3])
def test_k_zero_or_negative_returns_empty(k):
    assert top_k([1, 2, 3], k) == []

def test_empty_input():
    assert top_k([], 5) == []

def test_k_larger_than_input_returns_all_descending():
    assert top_k([4, 1, 3], 10) == [4, 3, 1]

def test_all_equal_values():
    assert top_k([7, 7, 7, 7], 2) == [7, 7]

def test_works_with_a_generator():
    assert top_k((x * x for x in range(10)), 3) == [81, 64, 49]

def test_matches_sorted_on_random_data():
    rng = random.Random(42)
    for _ in range(200):
        values = [rng.randint(0, 100) for _ in range(rng.randint(0, 300))]
        k = rng.randint(1, 20)
        assert top_k(values, k) == sorted(values, reverse=True)[:k]