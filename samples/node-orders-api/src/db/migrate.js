const { query } = require("./pool");

const STATEMENTS = [
  `CREATE TABLE IF NOT EXISTS customers (
     id SERIAL PRIMARY KEY,
     email TEXT UNIQUE NOT NULL,
     name TEXT NOT NULL
   )`,
  `CREATE TABLE IF NOT EXISTS orders (
     id SERIAL PRIMARY KEY,
     customer_id INTEGER REFERENCES customers(id),
     status TEXT NOT NULL DEFAULT 'new',
     total_cents INTEGER NOT NULL
   )`,
  `CREATE TABLE IF NOT EXISTS order_items (
     id SERIAL PRIMARY KEY,
     order_id INTEGER REFERENCES orders(id),
     sku TEXT NOT NULL,
     quantity INTEGER NOT NULL,
     price_cents INTEGER NOT NULL
   )`,
];

async function runMigrations() {
  for (const statement of STATEMENTS) {
    await query(statement, []);
  }
}

module.exports = { runMigrations };
