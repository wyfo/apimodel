# flake8: noqa
# type: ignore
import asyncio
import inspect
import json
import sys
import timeit
import typing
from typing import *
from unittest.mock import MagicMock

import pytest

from apischema import settings
from apischema.typing import (
    Annotated,
    Literal,
    TypedDict,
    Union,
    get_args,
    get_origin,
    is_type,
)

Union = Union  # to prevent import removal

typing.get_origin, typing.get_args = get_origin, get_args
typing.Annotated, typing.Literal, typing.TypedDict = Annotated, Literal, TypedDict
if "include_extras" not in inspect.signature(typing.get_type_hints).parameters:
    gth = typing.get_type_hints

    def get_type_hints(*args, include_extras=False, **kwargs):
        return gth(*args, **kwargs)

    typing.get_type_hints = get_type_hints
inspect.isclass = is_type
if sys.version_info < (3, 9):

    class CollectionABC:
        def __getattribute__(self, name):
            return globals()[name] if name in globals() else MagicMock()

    sys.modules["collections.abc"] = CollectionABC()
    del CollectionABC


class Wrapper:
    def __init__(self, cls):
        self.cls = cls
        self.implem = cls.__origin__

    def __getitem__(self, item):
        return self.cls[item]

    def __call__(self, *args, **kwargs):
        return self.implem(*args, **kwargs)

    def __instancecheck__(self, instance):
        return isinstance(instance, self.implem)

    def __subclasscheck__(self, subclass):
        return issubclass(subclass, self.implem)


for cls in (Dict, List, Set, FrozenSet, Tuple, Type):  # noqa
    wrapper = Wrapper(cls)
    globals()[wrapper.implem.__name__] = wrapper

Set = AbstractSet

del Wrapper

if sys.version_info < (3, 7):
    asyncio.run = lambda coro: asyncio.get_event_loop().run_until_complete(coro)

__timeit = timeit.timeit
timeit.timeit = lambda stmt, number=None, **kwargs: __timeit(stmt, number=1, **kwargs)

sys.modules["orjson"] = json

settings_classes = (
    settings,
    settings.errors,
    settings.base_schema,
    settings.deserialization,
    settings.serialization,
)
settings_dicts = {cls: dict(cls.__dict__) for cls in settings_classes}

## test body


def set_settings(dicts: Mapping[type, Mapping[str, Any]]):
    for cls, dict_ in dicts.items():
        for key, value in dict_.items():
            if not key.startswith("_"):
                setattr(cls, key, value)


test_dicts = {cls: dict(cls.__dict__) for cls in settings_classes}
set_settings(settings_dicts)


@pytest.fixture(autouse=True)
def test_settings(monkeypatch):
    set_settings(test_dicts)
    yield
    set_settings(settings_dicts)
