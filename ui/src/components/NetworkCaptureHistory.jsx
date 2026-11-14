import React, { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fetchCaptureHistory } from '../api'
import { capturePoints } from '../lib/captureHistory'

export default function NetworkCaptureHistory() {
  const [data, setData] = useState(null)
  const [hours, setHours] = useState(24)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    const refresh = async () => {
      try { const value = await fetchCaptureHistory(); if (active) { setData(value); setFailed(false) } }
      catch { if (active) setFailed(true) }
    }
    refresh()
    const timer = setInterval(refresh, 60000)
    return () => { active = false; clearInterval(timer) }
  }, [])
  const now = Date.now() / 1000
  const points = useMemo(() => capturePoints(data?.samples, now, hours), [data, hours, now])
  const stale = failed || data?.stale || !data?.generated || now - data.generated > 180
  return <section className="my-6 rounded-lg border border-gray-800 p-4">
    <div className="flex justify-between gap-3"><h2 className="text-lg text-white">Capture loss & mirror traffic</h2><select aria-label="Capture history range" className="bg-gray-900 text-gray-300" value={hours} onChange={e => setHours(Number(e.target.value))}><option value={1}>1 hour</option><option value={6}>6 hours</option><option value={24}>24 hours</option><option value={168}>7 days</option></select></div>
    <p className="text-xs text-gray-400 mt-2">Peak loss per minute (%) against mirror destination traffic (Mbps, interval average). Shared local-time axis; gaps mean missing observations. Short bursts may not appear in traffic averages.</p>
    {stale && <p className="text-amber-300 text-sm mt-2">Capture history is stale or unavailable. Retained observations are historical.</p>}
    {data?.generated && <p className="text-xs text-gray-400">Updated {new Date(data.generated * 1000).toLocaleString()}</p>}
    {points.length ? <div style={{width:'100%',height:300}}><ResponsiveContainer><LineChart data={points}><CartesianGrid stroke="#334155" strokeDasharray="3 3"/><XAxis dataKey="time" type="number" scale="time" domain={['dataMin','dataMax']} tickFormatter={v => new Date(v).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}/><YAxis yAxisId="loss" unit="%" stroke="#fbbf24" domain={[0, 'auto']}/><YAxis yAxisId="traffic" orientation="right" unit=" Mbps" stroke="#38bdf8" domain={[0, 'auto']}/><Tooltip labelFormatter={v => new Date(v).toLocaleString()} formatter={(v,name) => [`${Number(v).toFixed(3)} ${name === 'Capture loss' ? '%' : 'Mbps'}`, name]}/><Legend/><ReferenceLine yAxisId="loss" y={1} stroke="#f87171" strokeDasharray="4 4" label="1% alert threshold"/><Line yAxisId="loss" dataKey="loss" name="Capture loss" stroke="#fbbf24" dot={false} connectNulls={false} isAnimationActive={false}/><Line yAxisId="traffic" dataKey="traffic" name="Mirror traffic" stroke="#38bdf8" dot={false} connectNulls={false} isAnimationActive={false}/></LineChart></ResponsiveContainer></div> : <p className="text-gray-400 mt-3">Waiting for capture history.</p>}
  </section>
}
