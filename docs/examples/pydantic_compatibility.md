# *Pydantic* compatibility

It takes only 20 lines of code to support `pydantic.BaseModel` and all of its subclasses. You could add these lines to your project using *pydantic* and start to benefit of *Apischema* features, for example adding *GraphQL* API.

!!! note
    *pydantic* pseudo-dataclasses are de facto supported but without *pydantic* addition; they could be fully supported but it would requires some additional lines of code.  

```python
{!examples/pydantic_compatibility.py!}
```