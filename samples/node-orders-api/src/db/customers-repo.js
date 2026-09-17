const { query } = require("./pool");

async function findByEmail(email) {
  const rows = await query("SELECT * FROM customers WHERE email = $1", [email]);
  return rows[0] || null;
}

async function createCustomer(email, name) {
  const rows = await query(
    "INSERT INTO customers (email, name) VALUES ($1, $2) RETURNING *",
    [email, name]
  );
  return rows[0];
}

module.exports = { findByEmail, createCustomer };
