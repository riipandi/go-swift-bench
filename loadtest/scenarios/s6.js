// S6: POST /orders (insert dengan validasi), user_id acak
import { post } from '../lib/req.js';
import { pick } from '../lib/rng.js';
const STATUSES = ['pending', 'paid', 'shipped', 'cancelled'];
export function iteration(ctx) {
  const body = { user_id: pick(ctx.rng, ctx.data.users), total_cents: 500 + Math.floor(ctx.rng() * 499500),
    status: pick(ctx.rng, STATUSES), note: 'k6 order ' + Math.floor(ctx.rng() * 1e6) };
  post(ctx, '/orders', 'POST /orders', body, true);
}
