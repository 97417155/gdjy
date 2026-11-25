import { describe, expect, it } from 'vitest'
import { barOption, donutOption, lineOption, optionFromSpec } from '@/utils/charts'

describe('charts', () => {
  it('条形图按数据映射，标签超长截断', () => {
    const opt = barOption(['茂名高速公路机电EPC总承包工程', '珠海海上风电工程'], [6, 3], '万元')
    const series = opt.series as any[]
    expect(series[0].data.map((d: any) => d.value)).toEqual([6, 3])
    const yAxis = opt.yAxis as any
    expect(yAxis.data[0]).toBe('茂名高速公路机电EP…')
    expect(yAxis.data[1]).toBe('珠海海上风电工程')
  })

  it('折线图保留原始数值', () => {
    const opt = lineOption(['2026-05', '2026-06'], [42466.48, 41000], '万元')
    expect((opt.series as any[])[0].data).toEqual([42466.48, 41000])
    expect((opt.xAxis as any).data).toEqual(['26-05', '26-06'])
  })

  it('环形图超过 7 项时合并为"其他"，合计不丢数', () => {
    const labels = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
    const values = [10, 9, 8, 7, 6, 5, 4, 3]
    const opt = donutOption(labels, values, '万元')
    const data = (opt.series as any[])[0].data as { name: string; value: number }[]
    expect(data).toHaveLength(7)
    expect(data[6].name).toBe('其他')
    expect(data[6].value).toBe(4 + 3)
    expect(data.reduce((a, b) => a + b.value, 0)).toBe(values.reduce((a, b) => a + b, 0))
  })

  it('按后端 chart 规格选择图表类型', () => {
    const spec = { type: 'pie', labels: ['a'], series: [{ data: [1] }], unit: '万元' }
    expect(((optionFromSpec(spec).series as any[])[0]).type).toBe('pie')
  })
})
