class MinStack:
    def __init__(self):
        self._stack = []
        self._min_stack = []

    def push(self, val):
        self._stack.append(val)
        if not self._min_stack or val <= self._min_stack[-1]:
            self._min_stack.append(val)

    def pop(self):
        val = self._stack.pop()
        # BUG: always pops min_stack regardless of whether val is the min
        self._min_stack.pop()
        return val

    def get_min(self):
        return self._min_stack[-1]
