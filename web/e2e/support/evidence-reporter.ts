// Hosted evidence (WP-15 milestone 3): after a run, writes summary.json and summary.md next to
// the report, traces, videos and screenshots: what ran where, when, on which commit, what the
// target said about itself, and every test's outcome with its reasons. Skips say why (a router not
// deployed), and known bugs are listed, so "not measured" never hides behind a green total.
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

import type { FullConfig, FullResult, Reporter, TestCase, TestResult } from "@playwright/test/reporter";

interface Row {
  project: string;
  file: string;
  title: string;
  outcome: string;
  durationMs: number;
  notes: string[];
  attachments: string[];
}

const EXPECTED_FAILURE = "failed as expected (known bug)";
const ANSI = new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g");

function dhaka(date: Date): string {
  return `${date.toLocaleString("sv-SE", { timeZone: "Asia/Dhaka" })} Dhaka`;
}

function commit(): string {
  try {
    return execFileSync("git", ["rev-parse", "--short", "HEAD"], { encoding: "utf8" }).trim();
  } catch {
    return "unknown";
  }
}

export default class EvidenceReporter implements Reporter {
  private readonly dir: string;
  private readonly rows = new Map<string, Row>(); // by test id: the last attempt wins
  private config?: FullConfig;
  private started = new Date();

  constructor(options: { dir: string }) {
    this.dir = options.dir;
  }

  onBegin(config: FullConfig): void {
    this.config = config;
    this.started = new Date();
  }

  onTestEnd(test: TestCase, result: TestResult): void {
    const notes = [...test.annotations, ...result.annotations]
      .filter((annotation) => annotation.description)
      .map((annotation) => `${annotation.type}: ${annotation.description}`);
    if (result.error?.message) notes.push(`error: ${result.error.message.replace(ANSI, "").split("\n")[0]}`);
    const outcome = test.outcome();
    this.rows.set(test.id, {
      project: test.parent.project()?.name ?? "",
      file: relative(this.config?.rootDir ?? "", test.location.file).replace(/\\/g, "/"),
      title: test.titlePath().slice(3).join(" › ") || test.title,
      // An expected failure pins a known bug: say so rather than a bare "expected".
      outcome: test.expectedStatus === "failed" && outcome === "expected" ? EXPECTED_FAILURE : outcome,
      durationMs: result.duration,
      notes: [...new Set(notes)],
      attachments: result.attachments.filter((item) => item.path).map((item) => relative(this.dir, item.path ?? "").replace(/\\/g, "/")),
    });
  }

  async onEnd(result: FullResult): Promise<void> {
    const baseURL = String(this.config?.metadata?.baseURL ?? "");
    let health: unknown = null;
    try {
      health = await (await fetch(`${baseURL}/api/health`)).json();
    } catch (error) {
      health = { unreachable: String(error) };
    }
    const rows = [...this.rows.values()];
    const count = (outcome: string) => rows.filter((row) => row.outcome === outcome).length;
    const summary = {
      target: this.config?.metadata?.target,
      baseURL,
      started: this.started.toISOString(),
      finished: new Date().toISOString(),
      status: result.status,
      commit: commit(),
      playwright: this.config?.version,
      health,
      totals: {
        passed: count("expected"),
        knownBugFailures: count(EXPECTED_FAILURE),
        unexpected: count("unexpected"),
        flaky: count("flaky"),
        skipped: count("skipped"),
      },
      tests: rows.sort((a, b) => a.file.localeCompare(b.file) || a.title.localeCompare(b.title) || a.project.localeCompare(b.project)),
    };
    mkdirSync(this.dir, { recursive: true });
    writeFileSync(join(this.dir, "summary.json"), JSON.stringify(summary, null, 2));

    const knownBugs = [...new Set(rows.flatMap((row) => row.notes.filter((note) => note.startsWith("known bug: "))))].sort();
    const lines = [
      `# E2E evidence: ${summary.target} run`,
      "",
      `Target **${baseURL}** · ${dhaka(this.started)} · commit \`${summary.commit}\` · Playwright ${summary.playwright} · overall **${result.status}**`,
      "",
      "| Passed | Failed as expected (known bug) | Failed unexpectedly | Flaky | Skipped (not deployed) |",
      "| --- | --- | --- | --- | --- |",
      `| ${summary.totals.passed} | ${summary.totals.knownBugFailures} | ${summary.totals.unexpected} | ${summary.totals.flaky} | ${summary.totals.skipped} |`,
      "",
      "What the target reported about itself (`GET /api/health`):",
      "",
      "```json",
      JSON.stringify(health, null, 2),
      "```",
      "",
      "Each test ran on desktop Chrome and on a phone (Pixel 7) with a trace, a video and a final screenshot",
      "(`artifacts/`; open a trace with `npx playwright show-trace <file>`, or the HTML report in `report/`).",
      "",
      `## Known bugs pinned by this run (${knownBugs.length})`,
      "",
      ...(knownBugs.length ? knownBugs.map((bug) => `- ${bug.slice("known bug: ".length)}`) : ["None."]),
      "",
      "## Tests",
      "",
      "| Project | Test | Outcome | Time | Notes |",
      "| --- | --- | --- | --- | --- |",
      ...summary.tests.map((row) =>
        `| ${row.project} | ${row.file} › ${row.title} | ${row.outcome} | ${(row.durationMs / 1000).toFixed(1)} s | ${row.notes.filter((note) => !note.startsWith("known bug: ")).join("; ").replace(/\|/g, "\\|")} |`,
      ),
      "",
    ];
    writeFileSync(join(this.dir, "summary.md"), lines.join("\n"));
  }

  printsToStdio(): boolean {
    return false;
  }
}
