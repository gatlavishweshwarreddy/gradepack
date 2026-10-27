from collections import deque

_sentinel = object()

class BufferedIterator:
    """
    Wraps an iterable to provide lookahead and buffering.

    Public API:
    - __iter__ / __next__: iterator protocol. iter(x) must be x itself.
    - peek(index=0, default=_sentinel): return item `index` ahead without
      consuming. index 0 is the next item. If beyond end, return default
      if provided else raise StopIteration. Must not fetch more than
      index+1 items ahead. Raise ValueError for negative index.
    - has_next(): True if peek would succeed.
    - push_back(*values): push values back so next() returns them in the
      order of arguments. push_back(1,2) => next() is 1 then 2. Clears
      exhausted state.
    - take(n): consume and return list of next n items (fewer if exhausted).
      Must consume from buffer first.
    - window(size, step=1): yield tuples of length `size` sliding by `step`.
      Incomplete trailing windows are not yielded. Must respect buffered/
      pushed data and not over-consume. Raise ValueError for non-positive
      size/step.
    - close(): if underlying iterator has close(), delegate, clear buffer,
      mark exhausted. Subsequent next() raises StopIteration, has_next() is False.
    - throw(exc_type, exc_val=None, tb=None): if underlying has throw(),
      delegate (clearing buffer first) and return its result; otherwise raise.
    """
    def __init__(self, iterable):
        self._source = iterable
        self._source_iter = iter(iterable)
        self._buffer = deque()
        self._exhausted = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._buffer:
            return self._buffer.popleft()
        if self._exhausted:
            raise StopIteration
        try:
            return next(self._source_iter)
        except StopIteration:
            self._exhausted = True
            raise

    def peek(self, index=0, default=_sentinel):
        if index < 0:
            raise ValueError("index must be non-negative")
        while len(self._buffer) <= index:
            if self._exhausted:
                if default is not _sentinel:
                    return default
                raise StopIteration
            try:
                self._buffer.append(next(self._source_iter))
            except StopIteration:
                self._exhausted = True
                if default is not _sentinel:
                    return default
                raise
        return self._buffer[index]

    def has_next(self):
        try:
            self.peek()
            return True
        except StopIteration:
            return False

    def push_back(self, *values):
        if not values:
            return
        for v in reversed(values):
            self._buffer.appendleft(v)
        self._exhausted = False

    def take(self, n):
        if n <= 0:
            return []
        result = []
        for _ in range(n):
            try:
                result.append(next(self))
            except StopIteration:
                break
        return result

    def window(self, size, step=1):
        if size <= 0 or step <= 0:
            raise ValueError("size and step must be positive")
        buf = []
        for _ in range(size):
            try:
                buf.append(next(self))
            except StopIteration:
                return
        yield tuple(buf)
        while True:
            for _ in range(step):
                try:
                    buf.append(next(self))
                except StopIteration:
                    return
            buf = buf[step:]
            if len(buf) < size:
                return
            yield tuple(buf)

    def close(self):
        if hasattr(self._source_iter, 'close'):
            try:
                self._source_iter.close()
            except Exception:
                pass
        self._buffer.clear()
        self._exhausted = True

    def throw(self, exc_type, exc_val=None, tb=None):
        if hasattr(self._source_iter, 'throw'):
            self._buffer.clear()
            if exc_val is None and tb is None:
                return self._source_iter.throw(exc_type)
            elif tb is None:
                return self._source_iter.throw(exc_type, exc_val)
            else:
                return self._source_iter.throw(exc_type, exc_val, tb)
        if isinstance(exc_type, BaseException):
            raise exc_type.with_traceback(tb)
        if exc_val is not None:
            raise exc_type(exc_val).with_traceback(tb)
        raise exc_type().with_traceback(tb)