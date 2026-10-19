// Prints, after every run, the bugs this suite knows about and pins (expected failures and exact
// known lists, each annotated "known bug" with the work package that owns the fix), and writes
// them to test-results/known-bugs.json for the evidence bundle. A green run is not "no known
// issues": this list says what is still open.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import type { Reporter, TestCase, TestResult } from "@playwright/test/reporter";

import { WEB_DIR } from "./target";

export const KNOWN_BUG = "known bug";

export default class KnownBugsReporter implements Reporter {
  private readonly bugs = new Map<string, Set<string>>();

  onTestEnd(test: TestCase, result: TestResult): void {
    for (const annotation of [...test.annotations, ...result.annotations]) {
      if (annotation.type !== KNOWN_BUG || !annotation.description) continue;
      const projects = this.bugs.get(annotation.description) ?? new Set<string>();
      projects.add(test.parent.project()?.name ?? "");
      this.bugs.set(annotation.description, projects);
    }
  }

  onEnd(): void {
    const bugs = [...this.bugs.entries()].map(([description, projects]) => ({ description, projects: [...projects].sort() })).sort((a, b) => a.description.localeCompare(b.description));
    mkdirSync(join(WEB_DIR, "test-results"), { recursive: true });
    writeFileSync(join(WEB_DIR, "test-results", "known-bugs.json"), JSON.stringify(bugs, null, 2));
    if (bugs.length === 0) return;
    console.log(`\nKnown bugs pinned by this run (${bugs.length}); green does not mean none:`);
    for (const bug of bugs) console.log(`  - ${bug.description} [${bug.projects.join(", ")}]`);
  }

  printsToStdio(): boolean {
    return false;
  }
}
