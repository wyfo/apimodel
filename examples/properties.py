from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated

from apischema import deserialize, properties, schema
from apischema.json_schema import deserialization_schema


@dataclass
class Config:
    active: bool = True
    server_options: Mapping[str, bool] = field(
        default_factory=dict, metadata=properties(pattern=r"^server_")
    )
    client_options: Mapping[
        Annotated[str, schema(pattern=r"^client_")], bool  # noqa: F722
    ] = field(default_factory=dict, metadata=properties(...))
    options: Mapping[str, bool] = field(default_factory=dict, metadata=properties)


assert deserialize(
    Config,
    {"use_lightsaber": True, "server_auto_restart": False, "client_timeout": False},
) == Config(
    True,
    {"server_auto_restart": False},
    {"client_timeout": False},
    {"use_lightsaber": True},
)
assert deserialization_schema(Config) == {
    "$schema": "http://json-schema.org/draft/2020-12/schema#",
    "type": "object",
    "properties": {"active": {"type": "boolean", "default": True}},
    "additionalProperties": {"type": "boolean"},
    "patternProperties": {
        "^server_": {"type": "boolean"},
        "^client_": {"type": "boolean"},
    },
}
