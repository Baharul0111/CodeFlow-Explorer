import type { Sale, Totals } from "./types";

/** Add up the rows into the four numbers shown at the top of the page. */
export function calculateTotals(sales: Sale[]): Totals {
  if (sales.length === 0) {
    return { revenueCents: 0, units: 0, bestRegion: "—", averageOrderCents: 0 };
  }
  const revenueCents = sales.reduce((sum, sale) => sum + sale.revenueCents, 0);
  const units = sales.reduce((sum, sale) => sum + sale.units, 0);
  const byRegion = new Map<string, number>();
  for (const sale of sales) {
    byRegion.set(sale.region, (byRegion.get(sale.region) ?? 0) + sale.revenueCents);
  }
  const bestRegion = [...byRegion.entries()].sort((a, b) => b[1] - a[1])[0][0];
  return {
    revenueCents,
    units,
    bestRegion,
    averageOrderCents: Math.round(revenueCents / sales.length),
  };
}

export function formatMoney(cents: number): string {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" }).format(cents / 100);
}
