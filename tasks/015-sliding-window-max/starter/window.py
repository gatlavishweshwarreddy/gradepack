from collections import deque


def sliding_max(nums: list, k: int) -> list:
    """Return the maximum of each sliding window of size k."""
    if not nums or k <= 0:
        return []
    dq: deque[int] = deque()  # stores indices
    result = []
    for i, val in enumerate(nums):
        # Remove indices outside the window
        # BUG: should be `dq and dq[0] < i - k + 1` but uses wrong condition
        while dq and dq[0] >= i - k:
            dq.popleft()
        # Remove smaller elements from back
        while dq and nums[dq[-1]] <= val:
            dq.pop()
        dq.append(i)
        if i >= k - 1:
            result.append(nums[dq[0]])
    return result
