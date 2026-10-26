from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class Ledger:
    def __init__(self, initial_balance="0"):
        self._balance = Decimal(initial_balance)

    def add(self, amount_str: str) -> None:
        try:
            self._balance += Decimal(amount_str)
        except InvalidOperation:
            raise ValueError(f"Invalid amount: {amount_str!r}")

    def balance(self) -> str:
        return str(self._balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
