# End-to-end evidence (WP-15)

The 12 most important Playwright flows run against the **hosted** demo, on desktop Chrome and on a phone (Pixel 7),
with a trace, a video and a final screenshot for every test. This folder is what such a run
writes:

| File | What | In git |
| --- | --- | --- |
| `summary.md` | target, time (Dhaka), commit, what the target's `/api/health` reported, totals, every test's outcome with its reason (a skip names the router not deployed), and the known bugs the run observed | yes |
| `summary.json` | the same, machine-readable | yes |
| `artifacts/<test>/*.png` | final screenshot of each test | yes |
| `artifacts/<test>/trace.zip` | full trace: every action, DOM snapshot and network call (`npx playwright show-trace <file>`) | no (size) |
| `artifacts/<test>/video.webm` | video of the test | no (size) |
| `report/` | Playwright HTML report with all of the above | no (size) |

Traces and videos stay on the machine that ran the suite and in the CI artifact
`e2e-hosted-evidence` (workflow "E2E", job "hosted").

## Run it

```
E2E_BASE_URL=https://hishab.quadbits.net npm run e2e
```

or GitHub Actions -> E2E -> Run workflow -> target `hosted`; the job also runs after every
successful deploy. Requirements on the target: demo mode on (`DEMO_MODE=true`, public demo
accounts) and the synthetic universe seeded (`python -m app.facts.seed`), or the engines abstain.

## Reading the results

- A **skip** means the target has no router for that journey yet. It is never faked: the reason
  names the missing route.
- **Known bugs** lists the open bugs (owned by other work packages) that the flows checked and found
  still there. The run can be green while they are open; a fixed one drops off the list.
- Sessions the run used are signed out at the end, so cookies recorded in traces open nothing.
