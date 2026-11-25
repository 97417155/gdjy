import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TableDrawer from '@/components/TableDrawer.vue'

const detail = {
  table: 'FACT_CONTRACT',
  rows: 380,
  columns: [
    { name: 'CONTRACT_ID', type: 'TEXT', pk: true },
    { name: 'AMT', type: 'REAL', pk: false },
  ],
  samples: [{ CONTRACT_ID: 'HT00001', AMT: 1200.5 }],
  related_kpis: [{ kpi: 'HS_NEW_AMT', name: '新签合同额', unit: '万元' }],
  related_tables: [{ table: 'DIM_PROJECT', shared: ['PROJ_CODE'] }],
}

const tableMock = vi.fn()
vi.mock('@/api', () => ({
  api: { table: (name: string) => tableMock(name) },
}))

describe('TableDrawer', () => {
  beforeEach(() => {
    tableMock.mockReset()
    tableMock.mockResolvedValue(detail)
  })

  const mountDrawer = (open = true, table = 'FACT_CONTRACT') =>
    mount(TableDrawer, {
      props: { modelValue: open, table },
      global: { stubs: { teleport: true } },
    })

  it('打开时拉取表结构并渲染列定义', async () => {
    const w = mountDrawer()
    await flushPromises()
    expect(tableMock).toHaveBeenCalledWith('FACT_CONTRACT')
    expect(w.findAll('.col-row')).toHaveLength(2)
    expect(w.text()).toContain('CONTRACT_ID')
    expect(w.text()).toContain('380 行')
    expect(w.find('.tag.brand').text()).toBe('PK')
  })

  it('可切换到样例数据页签', async () => {
    const w = mountDrawer()
    await flushPromises()
    await w.findAll('.tab')[1].trigger('click')
    expect(w.find('table.sample').text()).toContain('HT00001')
  })

  it('展示相关指标与关联表，点击关联表抛 select', async () => {
    const w = mountDrawer()
    await flushPromises()
    expect(w.text()).toContain('新签合同额')
    const link = w.find('.chip.link')
    expect(link.text()).toContain('DIM_PROJECT')
    await link.trigger('click')
    expect(w.emitted('select')?.[0]).toEqual(['DIM_PROJECT'])
  })

  it('关闭时派发 update:modelValue=false', async () => {
    const w = mountDrawer()
    await flushPromises()
    await w.find('.close').trigger('click')
    expect(w.emitted('update:modelValue')?.[0]).toEqual([false])
  })

  it('接口失败时展示错误而不是崩溃', async () => {
    tableMock.mockRejectedValue(new Error('表不存在：X'))
    const w = mountDrawer(true, 'X')
    await flushPromises()
    expect(w.find('.err').text()).toContain('表不存在')
  })
})
