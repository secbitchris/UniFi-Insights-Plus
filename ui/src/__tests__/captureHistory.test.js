import { expect, it } from 'vitest'
import { capturePoints } from '../lib/captureHistory'
it('aligns observation times, preserves peak loss, and leaves missing minutes null', () => {
  const rows = capturePoints([{at:121,loss:1},{at:140,loss:7},{at:145,traffic:15,interval:60},{at:241,traffic:20}], 300, 1)
  expect(rows[0]).toMatchObject({time:120000,loss:7,traffic:15,interval:60})
  expect(rows[1]).toEqual({time:180000,loss:null,traffic:null})
  expect(rows[2]).toMatchObject({time:240000,loss:null,traffic:20})
  expect(rows[3]).toEqual({time:300000,loss:null,traffic:null})
})
it('ignores out-of-window samples and never fabricates an empty history', () => {
  expect(capturePoints([{at:1,loss:5},{at:9000,loss:3}],5000,1)).toEqual([])
})
