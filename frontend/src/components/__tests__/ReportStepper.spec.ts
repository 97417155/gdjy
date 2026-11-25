import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ReportStepper from '@/components/ReportStepper.vue'

describe('ReportStepper', () => {
  it('草稿状态：第一步 active，其余未激活', () => {
    const w = mount(ReportStepper, { props: { status: '草稿' } })
    const steps = w.findAll('.step')
    expect(steps).toHaveLength(5)
    expect(steps[0].classes()).toContain('active')
    expect(steps[1].classes()).not.toContain('done')
  })

  it('待审批状态：前两步 done，第三步 active', () => {
    const w = mount(ReportStepper, { props: { status: '待审批' } })
    const steps = w.findAll('.step')
    expect(steps[0].classes()).toContain('done')
    expect(steps[1].classes()).toContain('done')
    expect(steps[2].classes()).toContain('active')
    expect(w.findAll('.step-line.done')).toHaveLength(2)
  })

  it('已推送状态：全部完成，最后一步 active', () => {
    const w = mount(ReportStepper, { props: { status: '已推送' } })
    const steps = w.findAll('.step')
    expect(steps[4].classes()).toContain('active')
    expect(steps.slice(0, 4).every((s) => s.classes().includes('done'))).toBe(true)
  })

  it('未知状态回退到第一步', () => {
    const w = mount(ReportStepper, { props: { status: '???' } })
    expect(w.findAll('.step')[0].classes()).toContain('active')
  })
})
