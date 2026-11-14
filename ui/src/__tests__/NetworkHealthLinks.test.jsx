import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import NetworkHealthLinks from '../components/NetworkHealthLinks'

const sample = (at, speed) => ({
  at, connected: true, speed_mbps: speed,
  device: { uptime: 100, version: 'test' }, parent: { name: 'Test switch' },
  port: { port_idx: 2, rx_errors: 5, tx_errors: 0, link_down_count: 1, poe_good: true },
  local_port: { rx_errors: 2, tx_errors: 0 },
  deltas: { port: { status: 'reset', counters: {} } },
})
const incident = {
  id: 'test-1060', name: 'Test AP', status: 'active', expected_mbps: 1000,
  trigger_speed_mbps: 100, detected_at: 1060, previous_observed_at: 1000,
  before: [sample(1000, 1000)], samples: [sample(1060, 100)],
  events: [{ at: 1060, kind: 'speed changed', from: 1000, to: 100 }],
}

describe('Ethernet evidence', () => {
  it('shows the capture before rebooting, including previous speed and reset uncertainty', () => {
    render(<NetworkHealthLinks now={1100} report={{ generated: 1060, stale: false, incidents: [incident] }} />)
    expect(screen.getByRole('alert').textContent).toContain('before rebooting')
    expect(screen.getByText('1000 Mbps')).toBeTruthy()
    expect(screen.getByText('100 Mbps')).toBeTruthy()
    expect(screen.getAllByText(/5 total.*reset/)).toHaveLength(2)
    expect(screen.getByText(/native controller event history is not collected/)).toBeTruthy()
  })

  it('does not claim an active current fault when collection is stale', () => {
    render(<NetworkHealthLinks now={1500} report={{ generated: 1060, incidents: [incident] }} />)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('status').textContent).toContain('stale')
    expect(screen.getByText(/Test AP/)).toBeTruthy()
  })

  it('downloads the captured prior and trigger samples', async () => {
    let captured
    const oldCreate = URL.createObjectURL, oldRevoke = URL.revokeObjectURL
    URL.createObjectURL = vi.fn(blob => { captured = blob; return 'blob:test' })
    URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    try {
      render(<NetworkHealthLinks now={1100} report={{ generated: 1060, incidents: [incident] }} />)
      fireEvent.click(screen.getByText('Download evidence JSON'))
      const text = await new Promise(resolve => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result)
        reader.readAsText(captured)
      })
      const saved = JSON.parse(text)
      expect(saved.before[0].speed_mbps).toBe(1000)
      expect(saved.samples[0].speed_mbps).toBe(100)
      expect(click).toHaveBeenCalledOnce()
      await new Promise(resolve => setTimeout(resolve, 1050))
    } finally {
      click.mockRestore()
      URL.createObjectURL = oldCreate
      URL.revokeObjectURL = oldRevoke
    }
  })
})
