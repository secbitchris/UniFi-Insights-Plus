export function recent(time, now = Date.now()/1000) { return Number.isFinite(time) && now-time >= -60 && now-time <= 900 }
export function age(time, now = Date.now()/1000) {
  if (!Number.isFinite(time)) return 'not reported'
  const seconds = now-time
  if (seconds < -60) return 'clock ahead'
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds/60)} min ago`
  if (seconds < 86400) return `${Math.floor(seconds/3600)} hr ago`
  return `${Math.floor(seconds/86400)} days ago`
}
export const date = value => value ? new Date(value*1000).toLocaleString() : 'not reported'

