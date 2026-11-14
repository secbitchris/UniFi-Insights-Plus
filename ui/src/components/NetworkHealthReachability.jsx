import React from 'react'
import { recent, age, date } from '../lib/networkHealth'
export default function NetworkHealthReachability({reach,now}) { return (!!reach.length && <section className="mt-6 grid gap-3"><h2 className="text-lg text-white">Reachability by location</h2>{reach.map(row => {
      const fresh = row.status === 'received' && recent(row.fetched_at, now) && recent(row.summary?.generated, now)
      return <div className="rounded border border-gray-800 p-3 text-sm text-gray-300" key={row.name}><h3>{row.name} · {fresh ? 'current' : 'unavailable or stale'}</h3>
        <p className="text-xs text-gray-400 mt-1">Summary generated {age(row.summary?.generated, now)} · fetched {age(row.fetched_at, now)}</p>
        <table className="w-full mt-2 text-left"><thead><tr><th>Probe</th><th>Result</th><th>Latency</th><th>Last actual sample</th></tr></thead><tbody>{Object.entries(row.summary?.latest || {}).map(([target,value]) => {
          const current = fresh && recent(value.epoch, now)
          return <tr key={target}><td>{target}</td><td>{current ? value.result : 'unknown'}</td><td>{current && value.rtt ? `${value.rtt} ms` : '—'}</td><td title={date(value.epoch)}>{age(value.epoch, now)}</td></tr>
        })}</tbody></table>
        <p className="text-xs text-gray-500 mt-2">One failed ping is not an outage. Compare locations and targets. A fresh fetch does not make old samples current.</p>
      </div>
    })}</section>) }
