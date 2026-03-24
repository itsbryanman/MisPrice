import React, { useState, useEffect, useCallback } from 'react';

const API_BASE = process.env.REACT_APP_API_URL || '';

const CATEGORIES = [
  { value: '', label: 'All Categories' },
  { value: 'cpi', label: 'CPI / Inflation' },
  { value: 'fed_rate', label: 'Fed Rate' },
  { value: 'jobs', label: 'Jobs / Employment' },
  { value: 'gdp', label: 'GDP / Growth' },
  { value: 'housing', label: 'Housing' },
  { value: 'retail_sales', label: 'Retail Sales' },
  { value: 'trade', label: 'Trade' },
];

/* ---------- Reusable UI Components ---------- */

function Badge({ label, variant }) {
  const colors = {
    high: { bg: '#fef2f2', color: '#991b1b', border: '#fecaca' },
    medium: { bg: '#fffbeb', color: '#92400e', border: '#fde68a' },
    low: { bg: '#f0fdf4', color: '#166534', border: '#bbf7d0' },
    buy: { bg: '#eff6ff', color: '#1e40af', border: '#bfdbfe' },
    sell: { bg: '#fef2f2', color: '#991b1b', border: '#fecaca' },
    default: { bg: '#f3f4f6', color: '#374151', border: '#d1d5db' },
  };
  const c = colors[variant] || colors.default;
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 12,
      fontSize: 12, fontWeight: 600, background: c.bg, color: c.color,
      border: `1px solid ${c.border}`,
    }}>
      {label}
    </span>
  );
}

/* ---------- Divergence Table ---------- */

function DivergenceTable({ contracts }) {
  if (!contracts || contracts.length === 0) {
    return <p style={{ color: '#6b7280' }}>No divergences found.</p>;
  }
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
      <thead>
        <tr style={{ borderBottom: '2px solid #e5e7eb', textAlign: 'left' }}>
          <th style={{ padding: '8px 4px' }}>Contract</th>
          <th style={{ padding: '8px 4px' }}>Category</th>
          <th style={{ padding: '8px 4px', textAlign: 'right' }}>Kalshi</th>
          <th style={{ padding: '8px 4px', textAlign: 'right' }}>Model</th>
          <th style={{ padding: '8px 4px', textAlign: 'right' }}>Divergence</th>
          <th style={{ padding: '8px 4px' }}>Direction</th>
          <th style={{ padding: '8px 4px' }}>Confidence</th>
        </tr>
      </thead>
      <tbody>
        {contracts.map((c, i) => (
          <tr key={c.ticker || i} style={{ borderBottom: '1px solid #f3f4f6' }}>
            <td style={{ padding: '8px 4px', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                title={c.title}>{c.title || c.ticker}</td>
            <td style={{ padding: '8px 4px' }}>
              <Badge label={c.category} variant="default" />
            </td>
            <td style={{ padding: '8px 4px', textAlign: 'right', fontFamily: 'monospace' }}>
              {(c.kalshi_price * 100).toFixed(1)}%
            </td>
            <td style={{ padding: '8px 4px', textAlign: 'right', fontFamily: 'monospace' }}>
              {(c.model_probability * 100).toFixed(1)}%
            </td>
            <td style={{ padding: '8px 4px', textAlign: 'right', fontFamily: 'monospace',
                         color: c.divergence > 0 ? '#059669' : '#dc2626' }}>
              {c.divergence > 0 ? '+' : ''}{(c.divergence * 100).toFixed(1)}pp
            </td>
            <td style={{ padding: '8px 4px' }}>
              <Badge
                label={c.direction === 'kalshi_underpriced' ? 'BUY' : 'SELL'}
                variant={c.direction === 'kalshi_underpriced' ? 'buy' : 'sell'}
              />
            </td>
            <td style={{ padding: '8px 4px' }}>
              <Badge label={c.model_confidence} variant={c.model_confidence} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ---------- Calibration View ---------- */

function CalibrationView({ data }) {
  if (!data) return null;
  const summary = data.brier_summary || {};
  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Brier Score Summary</h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid #e5e7eb', textAlign: 'left' }}>
            <th style={{ padding: '6px 4px' }}>Category</th>
            <th style={{ padding: '6px 4px', textAlign: 'right' }}>Kalshi Brier</th>
            <th style={{ padding: '6px 4px', textAlign: 'right' }}>Model Brier</th>
            <th style={{ padding: '6px 4px', textAlign: 'right' }}>N</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(summary).map(([cat, s]) => (
            <tr key={cat} style={{ borderBottom: '1px solid #f3f4f6' }}>
              <td style={{ padding: '6px 4px', fontWeight: cat === 'overall' ? 700 : 400 }}>{cat}</td>
              <td style={{ padding: '6px 4px', textAlign: 'right', fontFamily: 'monospace' }}>
                {s.kalshi_brier?.toFixed(4)}
              </td>
              <td style={{ padding: '6px 4px', textAlign: 'right', fontFamily: 'monospace',
                           color: s.model_brier < s.kalshi_brier ? '#059669' : '#dc2626' }}>
                {s.model_brier?.toFixed(4)}
              </td>
              <td style={{ padding: '6px 4px', textAlign: 'right' }}>{s.n}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- Backtest View ---------- */

function BacktestView({ data }) {
  if (!data) return null;
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 16 }}>
        {[
          { label: 'Total P&L', value: `$${data.total_pnl?.toFixed(2)}`, color: data.total_pnl >= 0 ? '#059669' : '#dc2626' },
          { label: 'Trades', value: data.n_trades },
          { label: 'Win Rate', value: `${(data.win_rate * 100)?.toFixed(1)}%` },
          { label: 'Sharpe', value: data.sharpe_ratio?.toFixed(2) },
          { label: 'Max Drawdown', value: `$${data.max_drawdown?.toFixed(2)}` },
          { label: 'ROI', value: `${(data.roi * 100)?.toFixed(1)}%` },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ background: '#f9fafb', borderRadius: 8, padding: 12, textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: color || '#111827', marginTop: 4 }}>{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- Health View ---------- */

function HealthView({ data }) {
  if (!data) return null;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
      <div style={{ background: '#f0fdf4', borderRadius: 8, padding: 12, textAlign: 'center' }}>
        <div style={{ fontSize: 12, color: '#166534' }}>Status</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: '#166534' }}>{data.status}</div>
      </div>
      <div style={{ background: '#f9fafb', borderRadius: 8, padding: 12, textAlign: 'center' }}>
        <div style={{ fontSize: 12, color: '#6b7280' }}>Data Source</div>
        <div style={{ fontSize: 18, fontWeight: 700 }}>{data.data_source}</div>
      </div>
      <div style={{ background: '#f9fafb', borderRadius: 8, padding: 12, textAlign: 'center' }}>
        <div style={{ fontSize: 12, color: '#6b7280' }}>Contracts</div>
        <div style={{ fontSize: 18, fontWeight: 700 }}>{data.contract_count}</div>
      </div>
      <div style={{ background: '#f9fafb', borderRadius: 8, padding: 12, textAlign: 'center' }}>
        <div style={{ fontSize: 12, color: '#6b7280' }}>Uptime</div>
        <div style={{ fontSize: 18, fontWeight: 700 }}>{Math.floor(data.uptime_seconds || 0)}s</div>
      </div>
    </div>
  );
}

/* ---------- Main App ---------- */

function App() {
  const [tab, setTab] = useState('divergences');
  const [category, setCategory] = useState('');
  const [divergences, setDivergences] = useState(null);
  const [calibration, setCalibration] = useState(null);
  const [backtest, setBacktest] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async (endpoint, options = {}) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${API_BASE}${endpoint}`, options);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return await resp.json();
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'divergences') {
      const body = category ? { category } : {};
      fetchData('/divergences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(setDivergences);
    } else if (tab === 'calibration') {
      fetchData('/calibration').then(setCalibration);
    } else if (tab === 'backtest') {
      fetchData('/backtesting').then(setBacktest);
    } else if (tab === 'health') {
      fetchData('/health').then(setHealth);
    }
  }, [tab, category, fetchData]);

  const tabs = [
    { id: 'divergences', label: '📊 Divergences' },
    { id: 'calibration', label: '📈 Calibration' },
    { id: 'backtest', label: '💰 Backtest' },
    { id: 'health', label: '🏥 Health' },
  ];

  return (
    <div style={{ fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                  maxWidth: 1100, margin: '0 auto', padding: '24px 16px' }}>
      <header style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 28 }}>Crowd vs. Model</h1>
        <p style={{ margin: '4px 0 0', color: '#6b7280' }}>
          Prediction-market analysis dashboard
        </p>
      </header>

      {/* Tabs */}
      <nav style={{ display: 'flex', gap: 4, borderBottom: '2px solid #e5e7eb', marginBottom: 20 }}>
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: '8px 16px', cursor: 'pointer', border: 'none',
              background: tab === t.id ? '#fff' : 'transparent',
              borderBottom: tab === t.id ? '2px solid #2563eb' : '2px solid transparent',
              fontWeight: tab === t.id ? 600 : 400,
              color: tab === t.id ? '#2563eb' : '#6b7280',
              fontSize: 14, marginBottom: -2,
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* Category filter (divergences tab) */}
      {tab === 'divergences' && (
        <div style={{ marginBottom: 16 }}>
          <select
            value={category}
            onChange={e => setCategory(e.target.value)}
            style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid #d1d5db', fontSize: 14 }}
          >
            {CATEGORIES.map(c => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>
      )}

      {/* Loading / Error */}
      {loading && <p style={{ color: '#6b7280' }}>Loading…</p>}
      {error && <p style={{ color: '#dc2626' }}>Error: {error}</p>}

      {/* Content */}
      {!loading && !error && (
        <div style={{ background: '#fff', borderRadius: 8, border: '1px solid #e5e7eb', padding: 20 }}>
          {tab === 'divergences' && divergences && (
            <>
              {divergences.metadata && (
                <p style={{ margin: '0 0 12px', color: '#6b7280', fontSize: 13 }}>
                  {divergences.metadata.calibration_summary}
                </p>
              )}
              <DivergenceTable contracts={divergences.contracts} />
              {divergences.pagination && (
                <p style={{ fontSize: 12, color: '#9ca3af', marginTop: 8 }}>
                  Page {divergences.pagination.page} of {divergences.pagination.total_pages}
                  {' '}({divergences.pagination.total_items} total)
                </p>
              )}
            </>
          )}
          {tab === 'calibration' && <CalibrationView data={calibration} />}
          {tab === 'backtest' && <BacktestView data={backtest} />}
          {tab === 'health' && <HealthView data={health} />}
        </div>
      )}

      <footer style={{ marginTop: 32, textAlign: 'center', fontSize: 12, color: '#9ca3af' }}>
        Crowd vs. Model — API docs at{' '}
        <a href={`${API_BASE}/apidocs/`} style={{ color: '#2563eb' }}>/apidocs</a>
      </footer>
    </div>
  );
}

export default App;
