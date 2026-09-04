# Curation Strict MyPy Migration

## Goal

Remove every `curation/` path from `mypy-exceptions.txt` while keeping the
repository-wide strict check green:

```bash
just check-mypy
```

Migrations remain excluded by the command itself.

## Baseline

On 2026-08-29, removing all 42 `curation/` exclusions and running
`just check-mypy` produced **1,617 errors in 40 files**.

| Error code | Count | Primary cause |
| --- | ---: | --- |
| `no-untyped-call` | 642 | Calls into unannotated application and test helpers |
| `no-untyped-def` | 626 | Missing function, method, and callback annotations |
| `attr-defined` | 116 | Django model fields, generated methods, and related attributes are unknown |
| `var-annotated` | 97 | Django fields and ambiguous local collections lack types |
| `type-arg` | 80 | Bare `dict`, `list`, and `Callable` at JSON and LLM boundaries |
| other | 56 | Narrowing, assignment, overload, and return-contract issues |

The largest error sources are:

| File | Errors |
| --- | ---: |
| `curation/tests.py` | 342 |
| `curation/test_llm.py` | 189 |
| `curation/views.py` | 134 |
| `curation/test_fetch.py` | 116 |
| `curation/test_edit.py` | 110 |
| `curation/models/curation.py` | 92 |

The baseline is deliberately not kept active: all curation paths remain in
`mypy-exceptions.txt` until their slices are ready to remove.

## Root causes

### Django integration

`django-stubs` and `django-stubs-ext` are installed, but `mypy.ini` does not
enable `mypy_django_plugin.main`. Consequently, mypy does not recognize model
fields, generated `get_<field>_display()` methods, `<relation>_id` attributes,
or ORM manager/queryset APIs. This is responsible for a substantial part of
the model errors and their callers' cascades.

Enable and validate the plugin before annotating curation models. Its settings
module must match the normal checker environment, and plugin initialization
must not depend on unavailable services.

### Unannotated boundaries

The package has useful typed service objects, including
`games.gameinfo.GameInfo` used by curation, fetch and discovery stats, and
provider dataclasses, but several boundaries are intentionally dynamic at
runtime and currently untyped:

- Django models, views, commands, and test cases;
- persisted `JSONField` values;
- HTTP and `json.loads()` responses;
- OpenRouter request/response and tool-call payloads;
- decorator-attached LLM tool metadata and reflection.

Typing callers before these boundaries creates cascaded `no-untyped-call`
errors. Establish the boundary contracts first.

## Migration plan

Each slice must remove only the paths it makes compliant from
`mypy-exceptions.txt`, run the targeted strict check, and include its relevant
tests. Do not suppress diagnostics or weaken global strictness.

### 1. Establish the Django mypy baseline

- Configure `mypy_django_plugin.main` in `mypy.ini` and its Django settings
  module.
- Confirm the existing non-curation check is unchanged.
- Temporarily include only `curation/models/curation.py` and
  `curation/models/llm.py` to measure the post-plugin model baseline.
- Remove no exceptions in this preparatory slice unless the affected modules
  are fully clean.

### 2. Make the model layer strict

- Annotate every model method, classmethod, and `save()` override.
- Give `JSONField` data explicit application-level shapes at its read/write
  boundaries.
- Correct nullable queryset handling rather than relying on truthiness.
- Use typed model/queryset APIs supplied by the plugin; do not duplicate Django
  descriptors with incompatible handwritten annotations.
- Remove `curation/models/curation.py` and `curation/models/llm.py` from the
  exception list once clean.

### 3. Type pure data and provider services

Work from leaf modules upward:

- `games/gameinfo.py`, `curation/openrouter.py`, and `curation/providers.py`;
- `curation/fetch.py`, `curation/discovery.py`, and `curation/reconcile.py`;
- `curation/passes/` and `curation/merge.py`.

The focused `GameInfo` contract tests live at `games/tests/test_gameinfo.py`;
curation consumers and integration tests retain their current ownership.

At JSON/HTTP boundaries, parse into `TypedDict`, dataclass, or narrow
`object`-based values before business logic uses them. Avoid spreading `Any`
or using bare collection generics.

### 4. Define the LLM workflow contracts

- Type runner registration and tool decorators without dynamic undeclared
  attributes on bare `Callable` values.
- Define request, response, tool-call, tool-result, and persisted trajectory
  shapes.
- Make the abstract and concrete `run()` contracts agree, including skipped
  workflows that currently return `None`.
- Type `curation/llm.py` and all `curation/llm_runners/` modules together.

### 5. Type orchestration and HTTP entry points

- Annotate management-command `add_arguments()` and `handle()` methods,
  callback closures, and collection accumulators.
- Annotate task functions and admin helpers.
- Type URL decorators and all curation views with Django request/response
  types.
- Narrow request-body JSON and task kwargs before use.

### 6. Type tests alongside their production slices

Tests are strict-checked production code. For each completed production slice:

- annotate test methods as `-> None`;
- type factories, fake providers, and local callbacks;
- give mutable fixtures and recorded calls concrete collection types;
- correct actual fixture-shape errors exposed by strict inference.

The broad legacy `curation/tests.py` file should be its own final test slice;
it has 342 baseline errors.

### 7. Remove final exceptions and verify

After every curation path has been removed:

```bash
just check-mypy
just check
```

The final change must leave no `curation/` line in `mypy-exceptions.txt` and
pass the full repository check without diagnostic suppressions.

## Suggested slice order

1. Django plugin configuration.
2. Curation models and model-adjacent tests.
3. `gameinfo`, providers, fetch/discovery/reconcile, and their tests.
4. OpenRouter and LLM workflow/runners with their tests.
5. Passes, manual tools, commands, tasks, admin, URLs, and views.
6. Remaining integration tests and `curation/tests.py`.

This order minimizes cascades: type contracts before callers, production code
before its fakes, and models before ORM consumers.
