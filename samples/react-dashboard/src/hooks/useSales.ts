import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchSales } from "../lib/api";
import { calculateTotals } from "../lib/totals";
import type { DateRange, Sale } from "../lib/types";

/** Loads sales for a date range and keeps the page's loading and error state. */
export function useSales(range: DateRange) {
  const [sales, setSales] = useState<Sale[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchSales(range, controller.signal)
      .then((rows) => setSales(rows))
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(caught instanceof Error ? caught.message : "Could not load the sales");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [range.from, range.to, nonce]);

  const totals = useMemo(() => calculateTotals(sales), [sales]);
  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  return { sales, totals, loading, error, refresh };
}
