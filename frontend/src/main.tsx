import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import App from './App.tsx';
import { LiveRegionHost } from './components/a11y/LiveRegion';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
      <LiveRegionHost />
    </BrowserRouter>
  </React.StrictMode>,
);
