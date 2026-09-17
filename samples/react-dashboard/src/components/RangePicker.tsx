import type { DateRange } from "../lib/types";

export function RangePicker({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (range: DateRange) => void;
}) {
  return (
    <fieldset className="range">
      <legend>Date range</legend>
      <label>
        From
        <input
          type="date"
          value={value.from}
          onChange={(event) => onChange({ ...value, from: event.target.value })}
        />
      </label>
      <label>
        To
        <input
          type="date"
          value={value.to}
          onChange={(event) => onChange({ ...value, to: event.target.value })}
        />
      </label>
    </fieldset>
  );
}
