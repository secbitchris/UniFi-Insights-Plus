import React, { useEffect, useMemo, useState } from 'react'
import NetworkCaptureHistory from './NetworkCaptureHistory'
import NetworkHealthHistory from './NetworkHealthHistory'
import NetworkHealthReachability from './NetworkHealthReachability'
import NetworkHealthDevices from './NetworkHealthDevices'
import NetworkHealthLinks from './NetworkHealthLinks'
import { recent, age, date } from '../lib/networkHealth'
import { fetchNetworkHealth, fetchReachability, fetchNetworkHistory, fetchNetworkEvents, fetchNetworkLinks, setNetworkDevicePolicy } from '../api'

const color = { critical: 'text-red-400', warning: 'text-amber-300', unknown: 'text-slate-400', info: 'text-sky-300', ok: 'text-emerald-400' }
const rank = { critical: 0, warning: 1, unknown: 2, info: 3, ok: 4 }

export default function NetworkHealth() {
  const [data, setData] = useState(null)
  const [reach, setReach] = useState([])
  const [history, setHistory] = useState([])
  const [events, setEvents] = useState([])
  const [links, setLinks] = useState(null)
  const [error, setError] = useState('')
  const [range, setRange] = useState(24)
  const [saving, setSaving] = useState('')
  const [policyMessage, setPolicyMessage] = useState('')
  const [pending, setPending] = useState({})
  const now = Date.now()/1000
  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const [next, locations, past, changes, linkData] = await Promise.all([fetchNetworkHealth(), fetchReachability(), fetchNetworkHistory(), fetchNetworkEvents(), Promise.resolve(fetchNetworkLinks()).catch(() => null)])
        if (active) { setData(next); setReach(locations); setHistory(past); setEvents(changes); setLinks(linkData); setError(''); setPending(old => Object.fromEntries(Object.entries(old).filter(([mac,value]) => next.devices?.find(d => d.mac === mac)?.policy !== value))) }
      } catch { if (active) setError('Unable to refresh network health. Displayed results may be stale.') }
    }
    refresh()
    const timer = setInterval(refresh, 30000)
    return () => { active = false; clearInterval(timer) }
  }, [])
  const chart = useMemo(() => {
    const rows = history.filter(row => row.generated >= now-range*3600)
    const points = []
    rows.forEach((row,index) => {
      if (index && row.generated - rows[index-1].generated > 900) points.push({time:(rows[index-1].generated+1)*1000,Critical:null,Warning:null,Unknown:null})
      points.push({time:row.generated*1000,Critical:row.counts.critical || 0,Warning:row.counts.warning || 0,Unknown:row.counts.unknown || 0})
    })
    return points
  }, [history, range, now])
  const checks = [...(data?.checks || [])].sort((a,b) => (rank[a.severity] ?? 5)-(rank[b.severity] ?? 5))
  const stale = !!error || !!data?.stale || !recent(data?.generated, now)
  const savePolicy = async (device, status) => {
    setSaving(device.mac)
    try {
      const result = await setNetworkDevicePolicy(device.mac, status, device.policy_reason || '')
      setPending(value => ({...value, [device.mac]: status}))
      setPolicyMessage(`${device.name}: ${result.message}`)
    } catch { setPolicyMessage('Could not save device classification. No controller setting was changed.') }
    finally { setSaving('') }
  }
  return <section className="h-full overflow-auto p-4 md:p-6 max-w-6xl mx-auto w-full">
    <h1 className="text-xl font-semibold text-white">Network Health</h1>
    <p className="text-sm text-gray-400 mt-2">Checks run every five minutes. Unknown means evidence is missing, not healthy. Times below distinguish actual measurements from fetches.</p>
    <p className="text-sm text-gray-300 my-3">Last collection: {date(data?.generated)} · {age(data?.generated, now)}</p>
    {(error || stale) && <p role="alert" className="text-amber-300 mb-4">{error || 'Collection is stale. Do not treat these results as current.'}</p>}
    <div className="flex flex-wrap gap-4 mb-5">{Object.entries(data?.counts || {}).map(([severity,count]) => <span key={severity} className={stale ? color.unknown : color[severity]}>{count} {severity}</span>)}</div>
    <NetworkCaptureHistory/>
    <NetworkHealthLinks report={links} now={now}/>
    <div className="grid gap-3">
      {checks.map(check => <details key={check.title} className="rounded-lg border border-gray-800 bg-gray-900 p-4">
        <summary className="cursor-pointer flex justify-between gap-3"><span className="text-white">{check.title}</span><span className={stale ? color.unknown : color[check.severity] || color.unknown}>{stale ? 'stale' : check.severity || 'unknown'}</span></summary>
        <p className="text-sm text-gray-300 mt-3">{check.detail}</p>
        <p className="text-xs text-gray-400 mt-2">Status since {date(check.status_since)} · observed {age(check.last_observed, now)}{check.last_clear ? ` · last cleared ${date(check.last_clear)}` : ''}</p>
        {!!check.items?.length && <ul className="text-sm text-gray-400 list-disc pl-5 mt-2">{check.items.map((item, i) => <li key={i}>{String(item)}</li>)}</ul>}
        {!!check.ports?.length && <div className="overflow-x-auto mt-3"><table className="text-sm w-full text-left text-gray-300"><thead><tr><th>Port</th><th>New errors</th><th>Errors/min</th><th>Lifetime total</th><th>Evidence</th></tr></thead><tbody>{check.ports.map(p => <tr key={`${p.mac}:${p.port}`}><td>{p.device} · {p.port}</td><td>{p.new_errors ?? '—'}</td><td>{p.errors_per_minute ?? '—'}</td><td>{p.lifetime_errors}</td><td>{p.status}{p.interval_seconds ? ` · ${p.interval_seconds}s` : ''}</td></tr>)}</tbody></table></div>}
        {check.why && <p className="text-sm text-gray-400 mt-3">{check.why}</p>}
        {check.next_step && <p className="text-sm text-gray-300 mt-2">Next: {check.next_step}</p>}
        {!!check.devices?.length && <div className="flex flex-wrap gap-3 mt-3">{check.devices.map(d => <a className="text-sm text-teal-300 underline" key={d.mac} href={d.unifi_url} target="_blank" rel="noreferrer">{d.name} · {d.ip || d.mac} ↗</a>)}</div>}
      </details>)}
    </div>
    <NetworkHealthHistory chart={chart} events={events} range={range} setRange={setRange}/>
    <NetworkHealthReachability reach={reach} now={now}/>
    <NetworkHealthDevices devices={data?.devices || []} stale={stale} pending={pending} saving={saving} policyMessage={policyMessage} savePolicy={savePolicy} now={now}/>
    {!!Object.keys(data?.watch || {}).length && <section className="mt-6"><h2 className="text-lg text-white">Watched clients</h2><ul className="mt-2 space-y-2 text-sm text-gray-300">{Object.entries(data.watch).map(([mac,item]) => <li key={mac}>{item.label}: {stale ? 'stale' : item.status}{item.ap ? ` · ${item.ap}` : ''}{item.signal != null ? ` · ${item.signal} dBm` : ''}</li>)}</ul></section>}
  </section>
}
