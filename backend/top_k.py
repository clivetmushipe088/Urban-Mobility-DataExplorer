class MinHeap:
    """Array-backed binary min-heap with a key function.

    For the node at index i: parent = (i - 1) // 2, children = 2i + 1 and 2i + 2.
    Invariant: key(parent) <= key(child) for every node, so the smallest item is at index 0.
    push / pop: O(log n), peek: O(1), space: O(n). Equal keys have no guaranteed order.
    """

    def __init__(self, key=lambda x:x):
        self._items = []
        self._key = key

    def __len__(self) -> int:
        return len(self._items)

    def is_empty(self) -> bool:
        return len(self._items) == 0

    def peek(self):
        """Smallest item without removing it."""
        if self.is_empty():
            raise IndexError("peek from an empty heap")
        return self._items[0]

    def push(self, item) -> None:
        """Add at the end, then move it up until its parent is not larger."""
        self._items.append(item)
        self._sift_up(len(self._items) - 1)

    def pop(self):
        """Remove and return the smallest item."""
        if self.is_empty():
            raise IndexError("pop from an empty heap")
        smallest = self._items[0]
        last = self._items.pop()
        if self._items:
            self._items[0] = last
            self._sift_down(0)
        return smallest

    def _swap(self, i: int, j: int) -> None:
        self._items[i], self._items[j] = self._items[j], self._items[i]

    def _sift_up(self, i: int) -> None:

        while i > 0:
            parent = (i - 1) // 2
            if self._key(self._items[i]) < self._key(self._items[parent]):
                self._swap(i, parent)
                i = parent
            else:
                break


    def _sift_down(self, i: int) -> None:

        n = len(self._items)
        while True:
            left, right = 2 * i + 1, 2 * i + 2
            smallest = i
            if left < n and self._key(self._items[left]) < self._key(self._items[smallest]):
                smallest = left
            if right < n and self._key(self._items[right]) < self._key(self._items[smallest]):
                smallest = right
            if smallest == i:
                break
            self._swap(i, smallest)
            i = smallest

def top_k(items, k: int, key=lambda x: x) -> list:

    if k <= 0:
        return []
    heap = MinHeap(key)
    for item in items:
        if len(heap) < k:
            heap.push(item)
        elif key(item) > key(heap.peek()):
            heap.pop()
            heap.push(item)

    result = [None] * len(heap)
    for slot in range(len(result) -1, -1, -1):
        result[slot] = heap.pop()
    return result