import React from 'react'
import { age, date } from '../lib/networkHealth'

function download(incident) {
  const blob = new Blob([JSON.stringify(incident, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `ethernet-${incident.id.replace(/[^a-zA-Z0-9-]/g, '-')}.json`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function counterText(sample, endpoint) {
  const raw = sample[endpoint] || {}
  const delta = sample.deltas?.[endpoint]
  const total = (raw.rx_errors ?? 0) + (raw.tx_errors ?? 0)
  const known = raw.rx_errors != null && raw.tx_errors != null
  const values = delta?.counters || {}
  const measured = delta?.status === 'measured' && values.rx_errors != null && values.tx_errors != null
  return `${known ? total : '—'} total · ${measured ? values.rx_errors + values.tx_errors : '—'} new (${delta?.status || 'baseline'})`
}

export default function NetworkHealthLinks({ report, now }) {
  const retained = report?.incidents || []
  const active = retained.filter(x => x.status === 'active')
  const incidents = [...retained].sort((a,b) => Number(b.status === 'active')-Number(a.status === 'active') || b.detected_at-a.detected_at).slice(0,10)
  const monitored = (report?.observations || []).filter(x => x.policy === 'expected' && x.effective_expected_mbps >= 1000)
  const stale = !report || report.stale || !Number.isFinite(report.generated) || now-report.generated > 180 || report.generated-now > 60
  return <section className="mb-5 rounded-lg border border-gray-700 bg-gray-900 p-4">
    <h2 className="text-lg text-white">Ethernet link evidence</h2>
    <p className="text-sm text-gray-400 mt-2">Links are sampled every minute. A known or expected gigabit link reporting 100 Mbps or less captures its preceding observations and subsequent recovery. Evidence survives app and AP restarts.</p>
    <p className="text-sm text-gray-300 mt-2">{monitored.length} link(s) with a gigabit-or-faster expectation or learned baseline.</p>
    <p className="text-xs text-gray-400 mt-2">Last successful sample: {date(report?.generated)} · {age(report?.generated, now)}. Events are sampled transitions; native controller event history is not collected. Changes between samples may be missed.</p>
    {stale ? <p role="status" className="text-amber-300 mt-2">Link monitoring is unavailable or stale. Recorded incidents remain below.</p>
      : active.length ? <p role="alert" className="text-amber-300 mt-2">{active.length} unresolved Ethernet incident(s). Inspect or download the captured evidence before rebooting.</p>
        : <p className="text-emerald-400 text-sm mt-2">No unresolved Fast Ethernet incidents.</p>}
    {!incidents.length && <p className="text-sm text-gray-400 mt-2">No speed-drop incidents captured yet. Baselines are learned from observed gigabit links; explicit device speed expectations take precedence.</p>}
    {retained.length > 10 && <button className="text-sm text-teal-300 underline my-2" onClick={() => download({...report, id:'retained-history'})}>Download all retained evidence</button>}
    {incidents.map(incident => <details key={incident.id} open={incident.status === 'active'} className="mt-3 border-t border-gray-700 pt-3">
      <summary className="cursor-pointer text-gray-200">{incident.name} · {incident.expected_mbps} → {incident.trigger_speed_mbps} Mbps · {date(incident.detected_at)} · {incident.status}</summary>
      <p className="text-xs text-gray-400 mt-2">{incident.before?.length || 0} preceding sample(s). First observed {date(incident.detected_at)}; previous sample {date(incident.previous_observed_at)}.{incident.closed_at ? ` Closed ${date(incident.closed_at)}: ${incident.resolution}.` : ' Awaiting confirmed speed recovery or an expectation change.'}</p>
      <button className="text-sm text-teal-300 underline my-2" onClick={() => download(incident)}>Download evidence JSON</button>
      <div className="overflow-x-auto"><table className="text-xs text-gray-300 w-full text-left">
        <thead><tr><th>Sample</th><th>Link</th><th>AP uptime / firmware</th><th>Switch port</th><th>AP errors</th><th>Switch errors</th><th>Link-down count / PoE</th></tr></thead>
        <tbody>{[...(incident.before || []), ...(incident.samples || [])].map((sample, i) => <tr key={`${sample.at}-${i}`}>
          <td>{date(sample.at)}</td><td>{sample.connected === false ? 'offline' : sample.speed_mbps != null ? `${sample.speed_mbps} Mbps` : 'unknown'}</td>
          <td>{sample.device?.uptime ?? '—'} s / {sample.device?.version || '—'}</td>
          <td>{sample.parent?.name || 'unknown'} · {sample.port?.port_idx ?? '—'}</td>
          <td>{counterText(sample, 'local_port')}</td><td>{counterText(sample, 'port')}</td>
          <td>{sample.port?.link_down_count ?? '—'} / {sample.port?.poe_good == null ? 'unknown' : sample.port.poe_good ? 'good' : 'not good'}</td>
        </tr>)}</tbody>
      </table></div>
      <ul className="text-xs text-gray-400 mt-2">{(incident.events || []).map((event, i) => <li key={i}>{date(event.at)} · {event.kind}{event.from != null || event.to != null ? ` · ${JSON.stringify(event.from)} → ${JSON.stringify(event.to)}` : ''}{event.endpoint ? ` · ${event.endpoint}` : ''}</li>)}</ul>
    </details>)}
    <p className="text-xs text-gray-500 mt-3">Showing up to 10 incidents. Bounded retention: 10 preceding samples, up to 60 incident samples, and the latest 100 incidents for 30 days. No automatic reboot or port changes.</p>
  </section>
}
