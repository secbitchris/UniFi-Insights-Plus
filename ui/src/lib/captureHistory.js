// Minute buckets preserve peak loss; traffic is the observed interval average.
export function capturePoints(samples, now, hours) {
  const buckets = new Map()
  const start = Math.floor((now - hours * 3600) / 60) * 60
  const end = Math.floor(now / 60) * 60
  for (const sample of samples || []) {
    const time = Math.floor(sample.at / 60) * 60
    if (!Number.isFinite(time) || time < start || time > end) continue
    const row = buckets.get(time) || { time: time * 1000, loss: null, traffic: null }
    if (Number.isFinite(sample.loss)) row.loss = Math.max(row.loss ?? 0, sample.loss)
    if (Number.isFinite(sample.traffic)) { row.traffic = sample.traffic; row.interval = sample.interval }
    buckets.set(time, row)
  }
  if (!buckets.size) return []
  const first = Math.min(...buckets.keys())
  return Array.from({ length: (end - first) / 60 + 1 }, (_, i) => {
    const time = first + i * 60
    return buckets.get(time) || { time: time * 1000, loss: null, traffic: null }
  })
}
