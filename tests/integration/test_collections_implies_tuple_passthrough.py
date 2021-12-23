from typing import Tuple

import pytest

from apischema import PassThroughOptions, serialize


@pytest.mark.parametrize(
    "pass_through, expected_cls",
    [
        (None, list),
        (PassThroughOptions(tuple=True), tuple),
        (PassThroughOptions(collections=True), tuple),
    ],
)
def test_collections_implies_tuple_passthrough(pass_through, expected_cls):
    obj = (0, "")
    assert serialize(Tuple[int, str], obj, pass_through=pass_through) == expected_cls(
        obj
    )
