from dataclasses import dataclass, field
from typing import NewType

import pytest

from apischema import ValidationError, deserialize, schema

Tag = NewType("Tag", str)
schema(min_len=3, pattern=r"^\w*$", examples=["available", "EMEA"])(Tag)


@dataclass
class Resource:
    id: int
    tags: list[Tag] = field(
        default_factory=list,
        metadata=schema(
            description="regroup multiple resources", max_items=3, unique=True
        ),
    )


with pytest.raises(ValidationError) as err:  # pytest check exception is raised
    deserialize(
        Resource, {"id": 42, "tags": ["tag", "duplicate", "duplicate", "bad&", "_"]}
    )
assert err.value.errors == [
    {"loc": ["tags"], "err": "item count greater than 3 (maxItems)"},
    {"loc": ["tags"], "err": "duplicate items (uniqueItems)"},
    {"loc": ["tags", 3], "err": "not matching pattern ^\\w*$ (pattern)"},
    {"loc": ["tags", 4], "err": "string length lower than 3 (minLength)"},
]
