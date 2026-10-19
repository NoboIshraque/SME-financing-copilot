// Render the whole app against the offline mock API, as a signed-in demo user by default.
import { QueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { App } from "../App";
import { createMockDb, type MockDb } from "../mocks/db";
import { createMockFetch, type MockOverrides } from "../mocks/mockApi";

export const OWNER = "owner@hishab.demo";
export const ACCOUNTANT = "accountant@hishab.demo";
export const LENDER = "lender@hishab.demo";

export interface RenderAppOptions {
  /** Demo email to start signed in as; null starts signed out. */
  signedInAs?: string | null;
  overrides?: MockOverrides;
  db?: MockDb;
}

export function renderApp(path = "/", { signedInAs = OWNER, overrides, db }: RenderAppOptions = {}) {
  const state = db ?? createMockDb(signedInAs ? { signedInAs } : {});
  const fetchMock = vi.fn(createMockFetch({ db: state, overrides }));
  vi.stubGlobal("fetch", fetchMock);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const user = userEvent.setup();
  const view = render(<App initialPath={path} queryClient={queryClient} />);
  return { ...view, user, db: state, fetchMock, queryClient };
}

/** Paths the app requested from the API, in order. */
export function requestedPaths(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map(([input]) => String(input));
}
