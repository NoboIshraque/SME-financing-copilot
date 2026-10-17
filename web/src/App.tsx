import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, createMemoryRouter, RouterProvider } from "react-router-dom";

import { routes } from "./routes";

export function App({ initialPath, queryClient }: { initialPath?: string; queryClient?: QueryClient }) {
  const router = initialPath
    ? createMemoryRouter(routes, { initialEntries: [initialPath] })
    : createBrowserRouter(routes);
  const client = queryClient ?? new QueryClient({ defaultOptions: { queries: { retry: 1 } } });
  return (
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
