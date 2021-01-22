# Overview

## Apischema

Makes your life easier when it comes to python API.

JSON (de)serialization + *GraphQL* and JSON schema generation through python typing, with a spoonful of sugar.

## Install
```shell
pip install apischema
```
It requires only Python 3.6+ (and dataclasses [official backport](https://pypi.org/project/dataclasses/) for version 3.6 only)

*PyPy3* is fully supported.

## Why another library?

This library fulfills the following goals:

- stay as close as possible to the standard library (dataclasses, typing, etc.) — as a consequence do not need plugins for editors/linters/etc.;
- be additive and tunable, be able to work with user own types (ORM, etc.) as well as foreign libraries ones; do not need a PR for handling new types like `bson.ObjectId` or `collection.deque`;
- avoid dynamic things like using string for attribute name;
- support *GraphQL*;
- (*Bonus*) be the fastest.

No known alternative achieves all of this. 

!!! note
    Actually, *Apischema* is even adaptable enough to enable support of competitor libraries in a few dozens of line of code ([pydantic support example](examples/pydantic_support.md) using [conversions feature](conversions.md))  

## Example

```python
{!quickstart.py!}
```
*Apischema* works out of the box with you data model.

!!! note
    This example and further ones are using pytest stuff because they are in fact run as tests in the library CI
    
## *GraphQL*

*GraphQL* integration is detailed [further in the documentation](graphql/overview.md).

## FAQ

#### What is the difference between *Apischema* and *pydantic*?

See the [dedicated section](pydantic_difference.md), there is a lot of difference. 

#### I already have my data model with my *SQLAlchemy*/ORM tables, will I have to duplicate my code, making one dataclass by table?
Why would you have to duplicate them? *Apischema* can "work with user own types as well as foreign libraries ones". Some teasing of [conversion](conversions.md) feature: you can add default serialization for all your tables, or register different serializer that you can select according to your API endpoint, or both.

#### So *SQLAlchemy* is supported? Does it support other libraries?
No, in fact, no library are supported, even *SQLAlchemy*; it was a choice made to be as small and generic as possible, and to support only the standard library (with types like `datetime`, `UUID`). However, the library is flexible enough to code yourself the support you need with, I hope, the minimal effort. It's of course not excluded to add support in additional small plugin libraries. Feedbacks are welcome about the best way to do things.

#### I need more accurate validation than "ensure this is an integer and not a string ", can I do that?
See the [validation](validation.md) section. You can use standard JSON schema validation (`maxItems`, `pattern`, etc.) that will be embedded in your schema or add custom Python validators for each class/fields/`NewType` you want.

*Let's start the Apischema tour.*