from dataclasses import dataclass

from apischema.json_schema import deserialization_schema, serialization_schema
from apischema.tagged_unions import Tagged, TaggedUnion


@dataclass
class Bar:
    field: str


class Foo(TaggedUnion):
    bar: Tagged[Bar]
    baz: Tagged[int]


assert (
    deserialization_schema(Foo)
    == serialization_schema(Foo)
    == {
        "$schema": "http://json-schema.org/draft/2020-12/schema#",
        "type": "object",
        "properties": {
            "bar": {
                "type": "object",
                "properties": {"field": {"type": "string"}},
                "required": ["field"],
                "additionalProperties": False,
            },
            "baz": {"type": "integer"},
        },
        "additionalProperties": False,
        "minProperties": 1,
        "maxProperties": 1,
    }
)
