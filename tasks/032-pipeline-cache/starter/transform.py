class Transform:
    def __init__(self, fn, name):
        self.fn = fn
        self.name = name

    def apply(self, data):
        return self.fn(data)
