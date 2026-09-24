// Deterministic numerical fixtures. Never imported by the application.
function rng(seed) { let s = seed >>> 0; return () => { s = (1664525 * s + 1013904223) >>> 0; return s / 4294967296; }; }
export function barsFor(symbol = "FIXTURE", count = 504) {
  const random = rng([...symbol].reduce((s,c) => s * 31 + c.charCodeAt(0), 17));
  let price = 100;
  const date = new Date('2024-09-02T00:00:00Z');
  return Array.from({ length: count }, (_,i) => {
    while (date.getUTCDay() === 0 || date.getUTCDay() === 6) date.setUTCDate(date.getUTCDate() + 1);
    const open = price * (1 + (random() - .5) * .006);
    price = Math.max(1, open * (1 + .00065 + Math.sin(i / 29) * .0028 + (random() - .5) * .029));
    const bar = { date: date.toISOString().slice(0,10), open, close: price, high: Math.max(open,price) * (1 + random() * .011), low: Math.min(open,price) * (1 - random() * .011), volume: Math.round(1500000 + random() * 18000000) };
    date.setUTCDate(date.getUTCDate() + 1);
    return bar;
  });
}
