// S8: campuran 50% S3, 20% S4, 10% S5, 10% S6, 10% S7
import * as s3 from './s3.js';
import * as s4 from './s4.js';
import * as s5 from './s5.js';
import * as s6 from './s6.js';
import * as s7 from './s7.js';
export function iteration(ctx) {
  const r = ctx.rng();
  if (r < 0.5) s3.iteration(ctx);
  else if (r < 0.7) s4.iteration(ctx);
  else if (r < 0.8) s5.iteration(ctx);
  else if (r < 0.9) s6.iteration(ctx);
  else s7.iteration(ctx);
}
