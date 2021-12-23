from dataclasses import dataclass, field

import pytest

from apischema import ValidationError, deserialize
from apischema.metadata import required


@dataclass
class Foo:
    bar: int | None = field(default=None, metadata=required)


with pytest.raises(ValidationError) as err:
    deserialize(Foo, {})
assert err.value.errors == [{"loc": ["bar"], "err": "missing property"}]
