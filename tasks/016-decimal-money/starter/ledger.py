class Ledger:
    def __init__(self, initial_balance="0"):
        # BUG: stores as float, accumulates rounding error
        self._balance = float(initial_balance)

    def add(self, amount_str: str) -> None:
        try:
            self._balance += float(amount_str)
        except ValueError:
            raise ValueError(f"Invalid amount: {amount_str!r}")

    def balance(self) -> str:
        return f"{self._balance:.2f}"
