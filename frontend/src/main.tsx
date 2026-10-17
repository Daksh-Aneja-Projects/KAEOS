import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import App from './App.tsx';
import { LiveRegionHost } from './components/a11y/LiveRegion';
import ErrorBoundary from './components/ErrorBoundary';
import './index.css';

// A deploy replaces the hashed chunks; an open tab that then lazy-loads a page
// gets a 404. Reload once to pick up the new build. The sessionStorage guard
// makes it one-time so a genuinely broken deploy cannot reload in a loop.
window.addEventListener('vite:preloadError', (event) => {
  const KEY = 'kaeos-preload-reloaded';
  try {
    if (sessionStorage.getItem(KEY)) return;
    sessionStorage.setItem(KEY, '1');
  } catch {
    return;
  }
  event.preventDefault();
  window.location.reload();
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ErrorBoundary fallbackTitle="KAEOS could not load">
        <App />
      </ErrorBoundary>
      <LiveRegionHost />
    </BrowserRouter>
  </React.StrictMode>,
);
