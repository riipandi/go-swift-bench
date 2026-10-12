// S3: GET /users/{id} (baca by PK lewat ORM)
import { get } from '../lib/req.js';
import { pick } from '../lib/rng.js';
export function iteration(ctx) { get(ctx, '/users/' + pick(ctx.rng, ctx.data.users), 'GET /users/:id'); }
