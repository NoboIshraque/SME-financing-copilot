import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { createBrowserRouter, createMemoryRouter, RouterProvider } from "react-router-dom";

import { onUnauthorized } from "./api/client";
import { SESSION_KEY } from "./auth/session";
import { routes } from "./routes";

export function App({ initialPath, queryClient }: { initialPath?: string; queryClient?: QueryClient }) {
  const [router] = useState(() =>
    initialPath ? createMemoryRouter(routes, { initialEntries: [initialPath] }) : createBrowserRouter(routes),
  );
  const [client] = useState(() => queryClient ?? new QueryClient({ defaultOptions: { queries: { retry: 1 } } }));

  // Any 401 means the session ended: drop it, and the route guard sends the user to sign in.
  useEffect(() => onUnauthorized(() => client.setQueryData(SESSION_KEY, null)), [client]);

  return (
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
