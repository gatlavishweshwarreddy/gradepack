import datetime


class LogEntry:
    def __init__(self, time: datetime.time, level: str, message: str):
        self.time = time
        self.level = level
        self.message = message

    def __repr__(self):
        return f"LogEntry({self.time!r}, {self.level!r}, {self.message!r})"


def parse_log(lines):
    """Parse log lines of the form 'HH:MM:SS LEVEL message'."""
    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 2)
        if len(parts) < 3:
            continue
        time_str, level, message = parts
        h, m, s = time_str.split(":")
        t = datetime.time(int(h), int(m), int(s))
        entries.append(LogEntry(t, level, message))
    return entries
