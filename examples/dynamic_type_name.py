from dataclasses import dataclass

from apischema import type_name
from apischema.json_schema import serialization_schema


@dataclass
class Foo:
    pass


@dataclass
class Bar:
    pass


def foo_to_bar(_: Foo) -> Bar:
    return Bar()


type_name("Bars")(list[Bar])

assert serialization_schema(list[Foo], conversion=foo_to_bar, all_refs=True) == {
    "$schema": "http://json-schema.org/draft/2020-12/schema#",
    "$ref": "#/$defs/Bars",
    "$defs": {
        # Bars is present because `list[Foo]` is dynamically converted to `list[Bar]`
        "Bars": {"type": "array", "items": {"$ref": "#/$defs/Bar"}},
        "Bar": {"type": "object", "additionalProperties": False},
    },
}
