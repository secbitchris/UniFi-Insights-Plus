import React, { useEffect, useState } from 'react'
import { fetchNetworkHealth, fetchReachability, fetchNetworkHistory } from '../api'

const color = { critical: 'text-red-400', warning: 'text-amber-300', unknown: 'text-slate-400', info: 'text-sky-300', ok: 'text-emerald-400' }

export default function NetworkHealth() {
  const [data, setData] = useState(null)
  const [reach, setReach] = useState([])
  const [history, setHistory] = useState([])
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    const refresh = async () => {
      try { const [next, locations, past] = await Promise.all([fetchNetworkHealth(), fetchReachability(), fetchNetworkHistory()]); if (active) { setData(next); setReach(locations); setHistory(past); setError('') } }
      catch { if (active) setError('Unable to refresh network health. Displayed results may be stale.') }
    }
    refresh()
    const timer = setInterval(refresh, 30000)
    return () => { active = false; clearInterval(timer) }
  }, [])
  return <section className="overflow-auto p-4 md:p-6 max-w-6xl mx-auto w-full">
    <h1 className="text-xl font-semibold text-white">Network Health</h1>
    <p className="text-sm text-gray-400 mt-2">Gateway, Wi-Fi and switching checks collected every five minutes. Unknown means coverage is missing; it is not a passing result.</p>
    <p className="text-sm text-gray-300 my-3">{data?.generated ? `Last collected: ${new Date(data.generated * 1000).toLocaleString()}` : 'Waiting for the first collection.'}</p>
    {(error || data?.stale) && <p role="alert" className="text-amber-300 mb-4">{error || 'Collection is stale. Do not treat these results as current.'}</p>}
    {!!history.length && <p className="text-sm text-gray-400 mb-4">History: {history.length} collections retained, since {new Date(history[0].generated * 1000).toLocaleString()}. {history.filter(x => (x.counts.critical || x.counts.warning)).length} collections had warnings or critical findings.</p>}
    {!!reach.length && <div className="mb-5 grid gap-2"><h2 className="text-lg text-white">Reachability by location</h2>{reach.map(row => {
      const fresh = row.status === 'received' && Date.now()/1000 - row.fetched_at < 900 && Date.now()/1000 - (row.summary?.generated || 0) < 900
      return <div className="rounded border border-gray-800 p-3 text-sm text-gray-300" key={row.name}><h3>{row.name} · {fresh ? 'current' : 'unavailable or stale'}</h3>
        <table className="w-full mt-2 text-left"><thead><tr><th>Probe</th><th>Result</th><th>Latency</th></tr></thead><tbody>{Object.entries(row.summary?.latest || {}).map(([target, value]) => <tr key={target}><td>{target}</td><td>{fresh && Date.now()/1000 - value.epoch < 900 ? value.result : 'unknown'}</td><td>{value.rtt ? `${value.rtt} ms` : '—'}</td></tr>)}</tbody></table>
        <p className="text-xs text-gray-500 mt-2">Individual ping failures do not establish an outage. Compare locations and targets; missing samples are unknown.</p>
      </div>
    })}</div>}
    <div className="grid gap-3">
      {data?.checks?.map(check => <details key={check.title} className="rounded-lg border border-gray-800 bg-gray-900 p-4">
        <summary className="cursor-pointer flex justify-between gap-3"><span className="text-white">{check.title}</span><span className={color[check.severity] || color.unknown}>{data.stale || error ? 'stale' : check.severity}</span></summary>
        <p className="text-sm text-gray-300 mt-3">{check.detail}</p>
        {!!check.items?.length && <ul className="text-sm text-gray-400 list-disc pl-5 mt-2">{check.items.map((item, i) => <li key={i}>{String(item)}</li>)}</ul>}
        {check.why && <p className="text-xs text-gray-500 mt-3">{check.why}</p>}
      </details>)}
    </div>
    {!!Object.keys(data?.watch || {}).length && <div className="mt-6"><h2 className="text-lg text-white">Watched clients</h2><ul className="mt-2 space-y-2 text-sm text-gray-300">{Object.entries(data.watch).map(([mac, item]) => <li key={mac}>{item.label}: {data.stale || error ? 'stale' : item.status}{item.ap ? ` · ${item.ap}` : ''}{item.signal != null ? ` · ${item.signal} dBm` : ''}</li>)}</ul></div>}
  </section>
}
