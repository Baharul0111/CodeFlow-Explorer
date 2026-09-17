import { formatMoney } from "../lib/totals";
import type { Totals } from "../lib/types";

export function SummaryCards({ totals, loading }: { totals: Totals; loading: boolean }) {
  const cards = [
    { label: "Revenue", value: formatMoney(totals.revenueCents) },
    { label: "Units sold", value: String(totals.units) },
    { label: "Best region", value: totals.bestRegion },
    { label: "Average order", value: formatMoney(totals.averageOrderCents) },
  ];
  return (
    <section className="cards" aria-busy={loading}>
      {cards.map((card) => (
        <article key={card.label}>
          <h2>{card.label}</h2>
          <p>{loading ? "…" : card.value}</p>
        </article>
      ))}
    </section>
  );
}
