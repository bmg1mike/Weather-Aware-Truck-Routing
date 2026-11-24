import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import './styles.css';

const queryClient = new QueryClient({
  defaultOptions: {
    // Provider calls are expensive and budgeted: never refetch behind the user's back.
    queries: { refetchOnWindowFocus: false, retry: false, staleTime: 5 * 60 * 1000 },
    mutations: { retry: false },
  },
});

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root element');

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
