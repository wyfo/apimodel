from dataclasses import dataclass

from apischema.json_schema import deserialization_schema


@dataclass
class Foo:
    bar: int


def ref_factory(ref: str) -> str:
    return f"http://some-domain.org/path/to/{ref}.json#"


assert deserialization_schema(Foo, all_refs=True, ref_factory=ref_factory) == {
    "$schema": "http://json-schema.org/draft/2020-12/schema#",
    "$ref": "http://some-domain.org/path/to/Foo.json#",
}
