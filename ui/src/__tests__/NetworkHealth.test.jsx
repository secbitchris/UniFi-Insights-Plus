import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import NetworkHealth from '../components/NetworkHealth'
import { fetchNetworkHealth, fetchReachability, fetchNetworkHistory } from '../api'
vi.mock('../api', () => ({ fetchNetworkHealth: vi.fn(), fetchReachability: vi.fn(), fetchNetworkHistory: vi.fn() }))
describe('network health evidence', () => {
  it('labels stale results and client evidence explicitly', async () => {
    fetchNetworkHealth.mockResolvedValue({ generated: 1000, stale: true, checks: [{ title: 'DNS resolver', severity: 'ok', detail: 'Previous result' }], watch: { aa: { label: 'Camera', status: 'present' } } })
    fetchReachability.mockResolvedValue([])
    fetchNetworkHistory.mockResolvedValue([])
    render(<NetworkHealth />)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('stale'))
    expect(screen.getByText('Camera: stale')).toBeTruthy()
    expect(screen.queryByText('ok')).toBeNull()
  })
})
