from dataclasses import dataclass

from apischema import serialize
from apischema.fields import with_fields_set


# Decorator needed to benefit from the feature
@with_fields_set
@dataclass
class Foo:
    bar: int
    baz: str | None = None


assert serialize(Foo, Foo(0)) == {"bar": 0}
assert serialize(Foo, Foo(0), exclude_unset=False) == {"bar": 0, "baz": None}
