import { describe, expect, it } from 'vitest'
import { isNewerVersion } from '../components/ReleaseNotesModal'

describe('upstream version comparison for lab builds', () => {
  it.each(['3.7.2-lab.1', 'v3.7.2-lab.12'])('does not offer the included upstream version for %s', current => {
    expect(isNewerVersion('v3.7.2', current)).toBe(false)
  })

  it.each([
    ['v3.7.3', '3.7.2-lab.2', true],
    ['v3.8.0', '3.7.2-lab.2', true],
    ['v3.7.1', '3.7.2-lab.2', false],
    ['v3.7.2', '3.7.0-lab.5', true],
  ])('compares upstream %s with %s', (latest, current, expected) => {
    expect(isNewerVersion(latest, current)).toBe(expected)
  })

  it('retains real prerelease ordering', () => {
    expect(isNewerVersion('v3.7.2', '3.7.2-beta.1')).toBe(true)
    expect(isNewerVersion('v3.7.2-beta.1', '3.7.2')).toBe(false)
  })
})
