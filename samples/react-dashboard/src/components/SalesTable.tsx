import { formatMoney } from "../lib/totals";
import type { Sale } from "../lib/types";

export function SalesTable({ rows, loading }: { rows: Sale[]; loading: boolean }) {
  if (loading) {
    return <p>Loading sales…</p>;
  }
  if (rows.length === 0) {
    return <p>No sales in this range.</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Product</th>
          <th>Region</th>
          <th>Units</th>
          <th>Revenue</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((sale) => (
          <tr key={sale.id}>
            <td>{sale.soldOn}</td>
            <td>{sale.product}</td>
            <td>{sale.region}</td>
            <td>{sale.units}</td>
            <td>{formatMoney(sale.revenueCents)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
