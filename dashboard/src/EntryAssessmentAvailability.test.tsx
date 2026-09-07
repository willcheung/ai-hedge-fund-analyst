// SYNTHETIC regression inputs only; no research snapshot dependencies.
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {describe,it,expect} from 'vitest'
import {hasEntryAssessmentInputs,actionableEntryRows,CapitalPlanTable} from './App'

const row={symbol:'TEST',bucket:'Buy / Scout Now',actionMode:'Scout',capitalEligible:true,entryEligible:true,entryStatus:'inside_zone'}
const render=(rows: typeof row[])=>renderToStaticMarkup(createElement(CapitalPlanTable,{shortlistRows:rows,knownSymbols:new Set(['TEST']),shortlistStamp:''}))
describe('unavailable entry assessment is not a negative investment view',()=>{
 it('withholds counts/conclusions when publication removed required inputs',()=>{
  const withheld={...row,capitalEligible:undefined,bucket:'Assessment unavailable'}
  expect(hasEntryAssessmentInputs([withheld])).toBe(false)
  const html=render([withheld] as never)
  expect(html).toContain('Entry assessment unavailable')
  expect(html).not.toContain('No entries meet all criteria in this assessment')
 })
 it('retains evaluated positive and negative behavior without changing gates',()=>{
  expect(hasEntryAssessmentInputs([row])).toBe(true)
  expect(actionableEntryRows([row]).map(r=>r.symbol)).toEqual(['TEST'])
  const negative={...row,capitalEligible:false}
  expect(hasEntryAssessmentInputs([negative])).toBe(true)
  expect(actionableEntryRows([negative])).toEqual([])
  expect(render([negative])).toContain('No entries meet all criteria in this assessment')
  expect(render([row])).not.toContain('Entry assessment unavailable')
 })
 it('treats missing collection and unknown status as unavailable',()=>{
  expect(hasEntryAssessmentInputs([])).toBe(false)
  expect(hasEntryAssessmentInputs([{...row,actionMode:'Assessment unavailable'}])).toBe(false)
 })
})
