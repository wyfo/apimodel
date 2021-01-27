from dataclasses import dataclass
from typing import (
    Collection,
    Generic,
    List,
    Optional,
    Sequence,
    TypeVar,
)

from _pytest.python_api import raises
from pytest import mark

from apischema import schema_ref
from apischema.conversions import Conversion, LazyConversion
from apischema.json_schema import deserialization_schema, serialization_schema
from apischema.json_schema.generation.schema import DeserializationSchemaBuilder
from apischema.json_schema.refs import get_ref
from apischema.typing import Annotated


@schema_ref(None)
@dataclass
class A:
    a: int


@dataclass
class B:
    a: Optional[A]


schema_ref("Bs")(List[B])


@schema_ref("DD")
@dataclass
class D:
    bs: Annotated[List[B], schema_ref("Bs2")]  # noqa: F821


@dataclass
class Recursive:
    rec: Optional["Recursive"]


def test_find_refs():
    refs = {}
    DeserializationSchemaBuilder.RefsExtractor(refs).visit(D)
    DeserializationSchemaBuilder.RefsExtractor(refs).visit(Recursive)
    assert refs == {
        "B": (B, 1),
        "DD": (D, 1),
        "Bs": (List[B], 1),
        "Bs2": (Annotated[List[B], schema_ref("Bs2")], 1),
        "Recursive": (Recursive, 2),
    }


T = TypeVar("T")
U = TypeVar("U")


@dataclass
class DataGeneric(Generic[T]):
    a: T


schema_ref("StrData")(DataGeneric[str])


@mark.parametrize("cls", [DataGeneric, DataGeneric[U], DataGeneric[int]])
def test_generic_ref_error(cls):
    with raises(TypeError):
        schema_ref(...)(cls)


def test_generic_schema():
    schema_ref("StrData")(DataGeneric[str])
    assert deserialization_schema(DataGeneric, all_refs=True) == {
        "$schema": "http://json-schema.org/draft/2019-09/schema#",
        "type": "object",
        "properties": {"a": {}},
        "required": ["a"],
        "additionalProperties": False,
    }
    assert deserialization_schema(DataGeneric[int], all_refs=True) == {
        "$schema": "http://json-schema.org/draft/2019-09/schema#",
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    assert deserialization_schema(DataGeneric[str], all_refs=True) == {
        "$schema": "http://json-schema.org/draft/2019-09/schema#",
        "$ref": "#/$defs/StrData",
        "$defs": {
            "StrData": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
                "additionalProperties": False,
            }
        },
    }


def test_get_refs_of_replaced():
    schema_ref("test")(Sequence[A])
    assert get_ref(List[A]) == get_ref(Collection[A]) == "test"


class RecConv:
    pass


def rec_converter(rec: RecConv) -> List[RecConv]:
    ...


def test_recursive_conversion_without_ref():
    tmp = None
    conversion = Conversion(rec_converter, conversions=LazyConversion(lambda: tmp))
    tmp = conversion
    with raises(TypeError, match=r"Recursive type <.*> need a ref"):
        serialization_schema(RecConv, conversions=conversion)
