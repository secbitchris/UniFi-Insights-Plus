import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import NetworkHealth from '../components/NetworkHealth'
import { fetchNetworkHealth, fetchReachability, fetchNetworkHistory, fetchNetworkEvents, setNetworkDevicePolicy } from '../api'
vi.mock('../api', () => ({ fetchNetworkHealth: vi.fn(), fetchReachability: vi.fn(), fetchNetworkHistory: vi.fn(), fetchNetworkEvents: vi.fn(), setNetworkDevicePolicy: vi.fn() }))
describe('network health evidence', () => {
  it('labels stale results and client evidence explicitly', async () => {
    fetchNetworkHealth.mockResolvedValue({ generated: 1000, stale: true, checks: [{ title: 'DNS resolver', severity: 'ok', detail: 'Previous result' }], watch: { aa: { label: 'Camera', status: 'present' } } })
    fetchReachability.mockResolvedValue([])
    fetchNetworkHistory.mockResolvedValue([])
    fetchNetworkEvents.mockResolvedValue([])
    render(<NetworkHealth />)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('stale'))
    expect(screen.getByText('Camera: stale')).toBeTruthy()
    expect(screen.queryByText('ok')).toBeNull()
  })
})


it('separates old probe samples from a new fetch and hides stale latency', async () => {
  const now=Date.now()/1000
  fetchNetworkHealth.mockResolvedValue({generated:now,stale:false,checks:[],watch:{},devices:[]})
  fetchReachability.mockResolvedValue([{name:'Study',status:'received',fetched_at:now,summary:{generated:now-86400,latest:{'Internet-IP':{epoch:now-86400,result:'OK',rtt:'6.103'}}}}])
  fetchNetworkHistory.mockResolvedValue([])
  fetchNetworkEvents.mockResolvedValue([])
  render(<NetworkHealth />)
  await waitFor(() => expect(screen.getByText('Study · unavailable or stale')).toBeTruthy())
  expect(screen.queryByText('6.103 ms')).toBeNull()
  expect(screen.getByText(/Summary generated 1 days ago/)).toBeTruthy()
})

it('saves device expectations through the local monitor endpoint', async () => {
  const now=Date.now()/1000
  fetchNetworkHealth.mockResolvedValue({generated:now,stale:false,checks:[],watch:{},devices:[{mac:'aa:bb:cc:dd:ee:ff',name:'Old switch',policy:'expected',connected:false,last_seen:now-86400}]})
  fetchReachability.mockResolvedValue([])
  fetchNetworkHistory.mockResolvedValue([])
  fetchNetworkEvents.mockResolvedValue([])
  setNetworkDevicePolicy.mockResolvedValue({message:'Applied at the next scheduled collection.'})
  render(<NetworkHealth />)
  fireEvent.click(await screen.findByText(/Device expectations/))
  const select=await screen.findByRole('combobox',{name:'Expectation for Old switch'})
  fireEvent.change(select,{target:{value:'retired'}})
  await waitFor(() => expect(setNetworkDevicePolicy).toHaveBeenCalledWith('aa:bb:cc:dd:ee:ff','retired',''))
  expect(await screen.findByRole('status')).toBeTruthy()
})


it('offers intentionally offline separately from retired', async () => {
  const now=Date.now()/1000
  fetchNetworkHealth.mockResolvedValue({generated:now,stale:false,checks:[],watch:{},devices:[{mac:'aa:bb:cc:dd:ee:ff',name:'Planned switch',policy:'expected',connected:false,last_seen:now-86400}]})
  fetchReachability.mockResolvedValue([]); fetchNetworkHistory.mockResolvedValue([]); fetchNetworkEvents.mockResolvedValue([])
  setNetworkDevicePolicy.mockResolvedValue({message:'Saved'})
  render(<NetworkHealth />)
  fireEvent.click(await screen.findByText(/Device expectations/))
  const select=await screen.findByRole('combobox',{name:'Expectation for Planned switch'})
  fireEvent.change(select,{target:{value:'intentionally_offline'}})
  await waitFor(() => expect(setNetworkDevicePolicy).toHaveBeenCalledWith('aa:bb:cc:dd:ee:ff','intentionally_offline',''))
})
