# Distributions

The three libraries live as top-level packages in this repository (`commandport/`, `proclaunch/`,
`lifecycle_runner/`) and are published as separate distributions from the metadata here:

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
does not import or an import that is not declared). Build offline with
`pip wheel distributions/<name> --no-deps --no-build-isolation -w dist/`; publishing is the maintainer's step.
