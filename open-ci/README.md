# Open reproduction of ZiSE25's CI outputs

This fork adds `.github/workflows/open_reproduction.yml`, which reproduces the outputs of
[BUGSENG/ZiSE25](https://github.com/BUGSENG/ZiSE25)'s CI on GitHub-hosted runners. The
original workflow artifacts and logs have expired, and the upstream workflows need
BUGSENG's `saas.eclairit.com` runner and an ECLAIR license, so they cannot run here. They
are left in place and skip themselves outside `BUGSENG/ZiSE25`.

Every run uploads a report site as an artifact (kept 90 days) and, on pushes, deploys it
to this repository's GitHub Pages.

## What is reproduced with the same tools as upstream

| Output | How |
|---|---|
| Test results | `west twister -T tests --coverage --coverage-basedir . --platform native_sim`, the upstream command |
| Coverage | gcovr through twister, as upstream, plus an HTML report |
| Requirements document | `strictdoc export --formats=html temp_alert.sdoc` |
| Requirements hierarchy check | `scripts/check_requirements.py temp_alert.sdoc` |

## What is approximated with open-source stand-ins (not ECLAIR)

| Upstream ECLAIR output | Stand-in | Main difference |
|---|---|---|
| MISRA C:2025 and BARR-C findings | `open-ci/open_misra_check.py`: cppcheck's MISRA C:2012 addon | A subset of MISRA C:2012 only, no rule texts, runs on preprocessed code so Rule 20.x is skipped |
| Architecture (independence) findings | `open-ci/open_arch_check.py`: reads `ECLAIR/architecture.ecl` and checks uses with ctags | Identifier matching, not ECLAIR's program model |
| Requirements coverage (Directive 3.1) | `open-ci/open_trace_check.py`: checks `@implements` and `@tests` tags | Tag and comment matching only |

On pull requests the MISRA and architecture stand-ins also run on the base commit and fail
the run only on new findings, the same gating idea as upstream. The stand-ins are for
demonstration and teaching. They are not equivalent to ECLAIR and support no compliance
claim.

## Getting the real ECLAIR outputs

Follow the upstream README, "Forking the project": a self-hosted runner with Docker, and
ECLAIR installed under BUGSENG's free 30-day trial license (the 7-day trial is not
suitable). Then remove the `if: github.repository == 'BUGSENG/ZiSE25'` guards and point
`runs-on` at your runner. The upstream publish step posts results to BUGSENG's server
with their token, so in a fork you will probably want to upload the ECLAIR output
directory as an artifact instead.
