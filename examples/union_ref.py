from dataclasses import dataclass
from typing import Union

from graphql import print_schema

from apischema.graphql import graphql_schema


@dataclass
class Foo:
    foo: int


@dataclass
class Bar:
    bar: int


def foo_or_bar() -> Union[Foo, Bar]:
    ...


schema = graphql_schema(query=[foo_or_bar], union_ref="Or".join)
schema_str = """\
type Query {
  fooOrBar: FooOrBar!
}

union FooOrBar = Foo | Bar

type Foo {
  foo: Int!
}

type Bar {
  bar: Int!
}
"""
assert print_schema(schema) == schema_str
