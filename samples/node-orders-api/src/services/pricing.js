const TAX_RATE = 0.2;
const FREE_DELIVERY_OVER_CENTS = 5000;
const DELIVERY_CENTS = 499;

/** Add up the basket, add tax, and decide whether delivery is free. */
function priceBasket(items) {
  const subtotal = items.reduce((sum, item) => sum + item.priceCents * item.quantity, 0);
  const tax = Math.round(subtotal * TAX_RATE);
  const delivery = subtotal >= FREE_DELIVERY_OVER_CENTS ? 0 : DELIVERY_CENTS;
  return { subtotal, tax, delivery, total: subtotal + tax + delivery };
}

module.exports = { priceBasket, TAX_RATE };
