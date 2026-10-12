// S9: POST /orders/{id}/pay (transaksi dua tulisan), id dari pending_order_ids
import { post } from '../lib/req.js';
import { pick } from '../lib/rng.js';
export function iteration(ctx) { post(ctx, '/orders/' + pick(ctx.rng, ctx.data.pending) + '/pay', 'POST /orders/:id/pay', '', false); }
