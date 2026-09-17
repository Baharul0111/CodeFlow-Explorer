const { query, withTransaction } = require("./pool");

async function listOrders(status) {
  if (status) {
    return query("SELECT * FROM orders WHERE status = $1 ORDER BY id DESC", [status]);
  }
  return query("SELECT * FROM orders ORDER BY id DESC LIMIT 100", []);
}

async function getOrder(id) {
  const rows = await query("SELECT * FROM orders WHERE id = $1", [id]);
  return rows[0] || null;
}

async function getOrderItems(orderId) {
  return query("SELECT * FROM order_items WHERE order_id = $1", [orderId]);
}

/** Save an order and its lines together, so a half-written order can never exist. */
async function createOrder(customerId, items, totalCents) {
  return withTransaction(async (client) => {
    const inserted = await client.query(
      "INSERT INTO orders (customer_id, total_cents) VALUES ($1, $2) RETURNING *",
      [customerId, totalCents]
    );
    const order = inserted.rows[0];
    for (const item of items) {
      await client.query(
        "INSERT INTO order_items (order_id, sku, quantity, price_cents) VALUES ($1, $2, $3, $4)",
        [order.id, item.sku, item.quantity, item.priceCents]
      );
    }
    return order;
  });
}

async function setStatus(id, status) {
  const rows = await query("UPDATE orders SET status = $1 WHERE id = $2 RETURNING *", [status, id]);
  return rows[0] || null;
}

module.exports = { listOrders, getOrder, getOrderItems, createOrder, setStatus };
