import http from 'k6/http';

const JSON_HDR = { 'Content-Type': 'application/json' };
const ok200 = http.expectedStatuses(200);
const ok201 = http.expectedStatuses(201);

// phase: 'ramp' | 'steady' | 'warmup' (tag untuk submetric {phase:steady})
export function get(ctx, path, name) {
  return http.get(ctx.base + path, { tags: { name: name, phase: ctx.phase }, responseCallback: ok200 });
}

export function post(ctx, path, name, body, expectCreated) {
  return http.post(ctx.base + path, typeof body === 'string' ? body : JSON.stringify(body), {
    headers: JSON_HDR, tags: { name: name, phase: ctx.phase }, responseCallback: expectCreated ? ok201 : ok200,
  });
}

export function put(ctx, path, name, body) {
  return http.put(ctx.base + path, JSON.stringify(body), {
    headers: JSON_HDR, tags: { name: name, phase: ctx.phase }, responseCallback: ok200,
  });
}
