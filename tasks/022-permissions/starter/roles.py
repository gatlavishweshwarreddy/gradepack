from dataclasses import dataclass, field


@dataclass
class Role:
    name: str
    permissions: frozenset = field(default_factory=frozenset)

    def __post_init__(self):
        if not isinstance(self.permissions, frozenset):
            self.permissions = frozenset(self.permissions)
