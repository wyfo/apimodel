from dataclasses import dataclass

from apischema import identity, serialize, serializer
from apischema.conversions import Conversion


@dataclass
class RGB:
    red: int
    green: int
    blue: int

    @serializer
    @property
    def hexa(self) -> str:
        return f"#{self.red:02x}{self.green:02x}{self.blue:02x}"


assert serialize(RGB, RGB(0, 0, 0)) == "#000000"
# dynamic conversion used to bypass the registered one
assert serialize(RGB, RGB(0, 0, 0), conversion=identity) == {
    "red": 0,
    "green": 0,
    "blue": 0,
}
# Expended bypass form
assert serialize(
    RGB, RGB(0, 0, 0), conversion=Conversion(identity, source=RGB, target=RGB)
) == {"red": 0, "green": 0, "blue": 0}
