from apischema import deserialize, serialize
from apischema.json_schema import deserialization_schema
from apischema.objects import ObjectField, object_wrapper


class Foo:
    def __init__(self, bar):
        self.bar = bar


FooWrapper = object_wrapper(Foo, [ObjectField(name="bar", type=int, required=True)])

foo = deserialize(Foo, {"bar": 0}, conversions=FooWrapper.deserialization)
assert isinstance(foo, Foo) and foo.bar == 0
assert serialize(Foo(0), conversions=FooWrapper.serialization) == {"bar": 0}
assert deserialization_schema(Foo, conversions=FooWrapper.deserialization) == {
    "$schema": "http://json-schema.org/draft/2019-09/schema#",
    "type": "object",
    "properties": {"bar": {"type": "integer"}},
    "required": ["bar"],
    "additionalProperties": False,
}
