# Distributions

Each library lives inside its own distribution directory (`<name>/src/<package>/`), so every distribution is
self-contained and builds as a normal project:

```
commandport      <- no dependencies. The contract, the fakes, the scan.
   ^      ^
   |      +-- proclaunch        <- commandport, psutil. Detached services.
   |             ^
   +-- lifecycle-runner  <------+   run / capture / stream; reuses proclaunch's
                                    windowless flag and tree kill.
launch-runner    meta-package: the three above at matching versions.
```

Versions move together (`tests/test_distributions.py` fails on drift, and on a declared dependency that the code
does not import or an import that is not declared, and on an sdist that would build an empty wheel). Build with
`python -m build distributions/<name>` (or `pip wheel distributions/<name> --no-deps -w dist/`); publishing is the
maintainer's step.
