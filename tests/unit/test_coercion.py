import pytest

from apischema.deserialization.coercion import coerce
from apischema.types import NoneType


@pytest.mark.parametrize(
    "cls, data, result",
    [
        (int, 0, 0),
        (str, 0, "0"),
        (bool, 0, False),
        (bool, "true", True),
        (NoneType, "", None),
    ],
)
def test_coerce(cls, data, result):
    assert coerce(cls, data) == result


@pytest.mark.parametrize("cls, data", [(int, None), (bool, "I SAY NO"), (NoneType, 42)])
def test_coerce_error(cls, data):
    with pytest.raises(Exception):
        coerce(cls, data)
