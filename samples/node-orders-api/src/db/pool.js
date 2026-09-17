const { Pool } = require("pg");

const pool = new Pool({
  connectionString: process.env.DATABASE_URL || "postgres://localhost/orders",
  max: 10,
});

async function query(sql, params) {
  const started = Date.now();
  const result = await pool.query(sql, params);
  const took = Date.now() - started;
  if (took > 200) {
    console.warn("slow query", { sql, took });
  }
  return result.rows;
}

async function withTransaction(work) {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const result = await work(client);
    await client.query("COMMIT");
    return result;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

module.exports = { pool, query, withTransaction };
