import type { DateRange, Sale } from "./types";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:4000";

/** Ask the sales service for every sale in a date range. */
export async function fetchSales(range: DateRange, signal?: AbortSignal): Promise<Sale[]> {
  const query = new URLSearchParams({ from: range.from, to: range.to });
  const response = await fetch(`${BASE_URL}/api/sales?${query.toString()}`, { signal });
  if (!response.ok) {
    throw new Error(`The sales service answered with ${response.status}`);
  }
  const body = (await response.json()) as { sales: Sale[] };
  return body.sales;
}

export async function exportSales(range: DateRange): Promise<Blob> {
  const response = await fetch(`${BASE_URL}/api/sales/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(range),
  });
  if (!response.ok) {
    throw new Error("The export could not be created");
  }
  return response.blob();
}
