import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import DashboardApp from '../src/DashboardApp';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter basename="/analytics">
      <DashboardApp />
    </BrowserRouter>
  </React.StrictMode>,
);
