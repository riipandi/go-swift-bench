// S2: POST /bench/echo (decode + validasi + encode JSON ~1 KB)
import { post } from '../lib/req.js';

function buildBody() {
  const items = [];
  for (let i = 0; i < 6; i++) {
    items.push({ sku: 'SKU-' + (1000 + i), name: 'Benchmark item number ' + i, qty: 1 + i, price_cents: 1500 + i * 250, labels: ['label-a', 'label-b', 'label-' + i] });
  }
  return JSON.stringify({
    request_id: 'req-bench-0001',
    customer: { id: 42, name: 'Benchmark Customer', email: 'customer@example.test',
      address: { street: 'Jl. Benchmark No. 1', city: 'Jakarta', zip: '10110', country: 'ID' } },
    items: items,
    tags: ['alpha', 'beta', 'gamma', 'delta'],
    note: 'Echo payload used to measure decode, validate and encode of nested JSON.',
  });
}
const BODY = buildBody(); // ~1 KB

export function iteration(ctx) { post(ctx, '/bench/echo', 'POST /bench/echo', BODY, false); }
