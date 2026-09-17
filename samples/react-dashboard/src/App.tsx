import { useState } from "react";
import { SummaryCards } from "./components/SummaryCards";
import { SalesTable } from "./components/SalesTable";
import { RangePicker } from "./components/RangePicker";
import { useSales } from "./hooks/useSales";
import type { DateRange } from "./lib/types";

const DEFAULT_RANGE: DateRange = { from: "2026-01-01", to: "2026-03-31" };

export function App() {
  const [range, setRange] = useState<DateRange>(DEFAULT_RANGE);
  const { sales, totals, loading, error, refresh } = useSales(range);

  return (
    <main className="dashboard">
      <header>
        <h1>Sales</h1>
        <RangePicker value={range} onChange={setRange} />
        <button type="button" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {error ? <p className="error">{error}</p> : null}
      <SummaryCards totals={totals} loading={loading} />
      <SalesTable rows={sales} loading={loading} />
    </main>
  );
}
