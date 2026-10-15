# launch-runner

A meta-package: installing it installs the three libraries at matching versions.

| distribution | import name | what it is |
|---|---|---|
| `commandport` | `commandport` | the contract, the fakes and the scan |
| `lifecycle-runner` | `lifecycle_runner` | run / capture / stream a command to completion |
| `proclaunch` | `proclaunch` | detached background services with identity and readiness |

Install a single one when that is all you need: `commandport` has no dependencies, `proclaunch` needs only
`psutil`, and `lifecycle-runner` needs `commandport` and `psutil` (not `proclaunch`).
