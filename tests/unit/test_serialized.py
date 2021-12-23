from dataclasses import dataclass, field

from apischema import serialize, serialized
from apischema.json_schema import serialization_schema
from apischema.metadata import flatten


@dataclass
class Base:
    @serialized
    def serialized(self) -> int:
        return 0


base_schema = {
    "$schema": "http://json-schema.org/draft/2020-12/schema#",
    "type": "object",
    "properties": {"serialized": {"type": "integer"}},
    "required": ["serialized"],
    "additionalProperties": False,
}


@dataclass
class Inherited(Base):
    pass


@dataclass
class InheritedOverriden(Base):
    def serialized(self) -> int:
        return 1


def test_inherited_serialized():
    assert (
        serialization_schema(Base)
        == serialization_schema(Inherited)
        == serialization_schema(InheritedOverriden)
        == base_schema
    )
    assert (
        serialize(Base, Base())
        == serialize(Inherited, Inherited())
        == {"serialized": 0}
    )
    assert serialize(InheritedOverriden, InheritedOverriden()) == {"serialized": 1}


class WithFlattened(Base):
    base: Base = field(metadata=flatten)


def test_flattened_serialized():
    assert (
        serialization_schema(Base) == serialization_schema(WithFlattened) == base_schema
    )
    assert (
        serialize(Base, Base())
        == serialize(WithFlattened, WithFlattened())
        == {"serialized": 0}
    )
