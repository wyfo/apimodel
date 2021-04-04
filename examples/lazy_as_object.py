from apischema import deserialize, serialize
from apischema.objects import ObjectField, as_object


class Foo:
    def __init__(self, bar: int):
        self.bar = bar


as_object(Foo, lambda: [ObjectField("bar", int, required=True)])

foo = deserialize(Foo, {"bar": 0})
assert type(foo) == Foo and foo.bar == 0
assert serialize(Foo(0)) == {"bar": 0}
