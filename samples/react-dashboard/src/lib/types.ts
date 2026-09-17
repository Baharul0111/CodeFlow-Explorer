export interface DateRange {
  from: string;
  to: string;
}

export interface Sale {
  id: string;
  soldOn: string;
  product: string;
  region: string;
  units: number;
  revenueCents: number;
}

export interface Totals {
  revenueCents: number;
  units: number;
  bestRegion: string;
  averageOrderCents: number;
}
