const { HttpError } = require("../middleware/errors");
const repo = require("../db/orders-repo");
const customers = require("../db/customers-repo");
const { priceBasket } = require("./pricing");

const ALLOWED_STATUS = ["new", "packing", "sent", "cancelled"];

/** Check the basket, work out the price, find or create the customer, then save. */
async function placeOrder({ email, name, items }) {
  if (!Array.isArray(items) || items.length === 0) {
    throw new HttpError(400, "An order needs at least one item");
  }
  for (const item of items) {
    if (!item.sku || item.quantity <= 0) {
      throw new HttpError(400, "Every item needs a product code and a quantity");
    }
  }
  const price = priceBasket(items);
  let customer = await customers.findByEmail(email);
  if (!customer) {
    customer = await customers.createCustomer(email, name || email);
  }
  const order = await repo.createOrder(customer.id, items, price.total);
  return { ...order, price };
}

async function readOrder(id) {
  const order = await repo.getOrder(id);
  if (!order) {
    throw new HttpError(404, "That order does not exist");
  }
  const items = await repo.getOrderItems(order.id);
  return { ...order, items };
}

async function changeStatus(id, status) {
  if (!ALLOWED_STATUS.includes(status)) {
    throw new HttpError(400, "That is not a status we use");
  }
  const updated = await repo.setStatus(id, status);
  if (!updated) {
    throw new HttpError(404, "That order does not exist");
  }
  return updated;
}

module.exports = { placeOrder, readOrder, changeStatus, ALLOWED_STATUS };
