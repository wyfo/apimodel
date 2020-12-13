__all__ = [
    "Undefined",
    "UndefinedType",
    "Unsupported",
    "ValidationError",
    "alias",
    "conversions",
    "dataclasses",
    "deserialization",
    "deserialize",
    "deserializer",
    "fields",
    "json_schema",
    "metadata",
    "properties",
    "reset_cache",
    "schema",
    "schema_ref",
    "serialization",
    "serialize",
    "serialized",
    "serializer",
    "settings",
    "skip",
    "validation",
    "validator",
]


from . import (
    conversions,
    dataclasses,
    fields,
    json_schema,
    metadata,
    serialization,
    settings,
    skip,
    validation,
)
from .aliases import alias
from .cache import reset_cache
from .conversions import deserializer, serializer
from .deserialization import deserialize
from .json_schema.refs import schema_ref
from .json_schema.schema import schema
from .metadata import properties
from .serialization import serialize, serialized
from .utils import Undefined, UndefinedType
from .validation import ValidationError, validator
from .visitor import Unsupported

try:
    from . import graphql  # noqa: F401

    __all__.append("graphql")
except ImportError:
    pass


def __getattr__(name):
    if name == "graphql":
        raise AttributeError(
            "GraphQL feature requires graphql-core library\n"
            "Run `pip install apischema[graphql]` to install it"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def default_conversions():
    """Handle standard library + internal types"""
    from typing import Sequence
    from . import std_types  # noqa: F401
    from .validation.errors import LocalizedError

    deserializer(ValidationError.deserialize, Sequence[LocalizedError], ValidationError)
    serializer(ValidationError.serialize, ValidationError)


default_conversions()
del default_conversions  # clean namespace
