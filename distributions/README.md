# Distributions

Each library lives inside its own distribution directory (`<name>/src/<package>/`), so every distribution is
self-contained and builds as a normal project:

```
commandport      <- no dependencies. The scan; imports none of the libraries it checks.
   ^      ^
   |      +-- proclaunch        <- commandport, psutil. Detached services.
   |
   +-- lifecycle-runner  <- commandport, psutil. run / capture / stream; independent of proclaunch.
launch-runner    meta-package: the three above at matching versions.
```

Each distribution has its own version, and the release gate (`tests/test_distributions.py`) enforces how they relate:
`commandport`, `proclaunch` and `lifecycle-runner` depend on no sibling (each installs alone); a library built on
them (`ensure-running`) declares bounded ranges (`>=lower,<upper`) and imports only the siblings' public `api`
modules, whose `__all__` is the compatibility surface; `launch-runner` pins the exact tested set. While the major
version is 0, a minor release may break the public surface and a patch release may not, so upper bounds are the
next minor. The gate also fails on a declared dependency that the code does not import, an import that is not
declared, and an sdist that would build an empty wheel. Build with
`python -m build distributions/<name>` (or `pip wheel distributions/<name> --no-deps -w dist/`); publishing is the
maintainer's step.
