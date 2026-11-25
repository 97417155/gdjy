/** ECharts 配置构造器：统一配色、字号与留白，视图只传数据 */
import type { EChartsOption } from 'echarts'
import { fmt, fmtInt } from './format'

export const PALETTE: string[] = ['#1f5fa9', '#4a86c6', '#8fb4dd', '#b9cfe8', '#d9b26a', '#c98b3f', '#9aa7b6', '#cfd6de']
const AXIS_TEXT = { color: '#93a0af', fontSize: 11 }
const SPLIT_LINE = { lineStyle: { color: '#eef1f5' } }

const tooltipBase = (unit: string) => ({
  trigger: 'axis' as const,
  axisPointer: { type: 'shadow' as const, shadowStyle: { color: 'rgba(31,95,169,.05)' } },
  backgroundColor: 'rgba(27,36,48,.92)',
  borderWidth: 0,
  padding: [7, 10] as [number, number],
  textStyle: { color: '#fff', fontSize: 12 },
  formatter: (ps: any): string => {
    const p = Array.isArray(ps) ? ps[0] : ps
    const v = Number(p?.value ?? 0)
    return `${p?.name ?? ''}<br/><b>${unit === '%' ? fmt(v, 1) + '%' : fmtInt(v) + ' ' + unit}</b>`
  },
})

export function barOption(
  labels: string[], data: number[], unit = '万元', max = 8,
): EChartsOption {
  const rows = labels.map((l, i) => ({ l, v: Number(data[i] || 0) })).slice(0, max)
  return {
    grid: { left: 8, right: 56, top: 8, bottom: 4, containLabel: true },
    tooltip: tooltipBase(unit),
    xAxis: {
      type: 'value', axisLabel: AXIS_TEXT, splitLine: SPLIT_LINE,
      axisLine: { show: false }, axisTick: { show: false },
    },
    yAxis: {
      type: 'category', inverse: true,
      data: rows.map((r) => (r.l && r.l.length > 10 ? r.l.slice(0, 10) + '…' : r.l || '—')),
      axisLabel: { ...AXIS_TEXT, color: '#5a6675', fontSize: 11.5 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      data: rows.map((r, i) => ({
        value: r.v,
        itemStyle: { color: i === 0 ? PALETTE[0] : PALETTE[2], borderRadius: [0, 3, 3, 0] as [number, number, number, number] },
      })),
      barWidth: 16,
      label: {
        show: true, position: 'right', fontSize: 11, color: '#1b2430',
        formatter: (p: any) => (unit === '%' ? fmt(p.value, 1) + '%' : fmtInt(p.value)),
      },
    }],
  }
}

export function lineOption(labels: string[], data: number[], unit = '万元'): EChartsOption {
  return {
    grid: { left: 8, right: 18, top: 18, bottom: 4, containLabel: true },
    tooltip: { ...tooltipBase(unit), axisPointer: { type: 'line', lineStyle: { color: '#b9cfe8' } } },
    xAxis: {
      type: 'category', boundaryGap: false,
      data: labels.map((l) => String(l).slice(2)),
      axisLabel: AXIS_TEXT, axisLine: { lineStyle: { color: '#e5e9ef' } }, axisTick: { show: false },
    },
    yAxis: { type: 'value', axisLabel: { ...AXIS_TEXT, formatter: (v: number) => fmtInt(v) }, splitLine: SPLIT_LINE },
    series: [{
      type: 'line', data, smooth: 0.25, symbolSize: 6,
      lineStyle: { width: 2, color: PALETTE[0] },
      itemStyle: { color: '#fff', borderColor: PALETTE[0], borderWidth: 1.8 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(31,95,169,.16)' },
            { offset: 1, color: 'rgba(31,95,169,0)' },
          ],
        },
      },
    }],
  }
}

export function donutOption(labels: string[], data: number[], unit = '万元'): EChartsOption {
  let items = labels
    .map((l, i) => ({ name: l || '其他', value: Number(data[i] || 0) }))
    .filter((d) => d.value > 0)
    .sort((a, b) => b.value - a.value)
  if (items.length > 7) {
    const head = items.slice(0, 6)
    const rest = items.slice(6).reduce((a, b) => a + b.value, 0)
    items = head.concat([{ name: '其他', value: rest }])
  }
  const total = items.reduce((a, b) => a + b.value, 0)
  return {
    color: PALETTE,
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(27,36,48,.92)',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (p: any) => `${p.name}<br/><b>${fmtInt(p.value)} ${unit}</b> · ${p.percent}%`,
    },
    legend: {
      orient: 'vertical', right: 0, top: 'middle',
      itemWidth: 8, itemHeight: 8, itemGap: 10,
      textStyle: { color: '#3a4450', fontSize: 11.5 },
      formatter: (name: string) => {
        const it = items.find((i) => i.name === name)
        const p = it && total ? ((it.value / total) * 100).toFixed(1) : '0.0'
        return `${name}  ${p}%`
      },
    },
    series: [{
      type: 'pie',
      radius: ['54%', '76%'],
      center: ['32%', '50%'],
      label: { show: false },
      labelLine: { show: false },
      itemStyle: { borderColor: '#fff', borderWidth: 1.5 },
      data: items,
    }],
    graphic: [
      { type: 'text', left: 'center', top: '44%', style: { text: '合计', fill: '#93a0af', fontSize: 10.5, align: 'center' } },
      { type: 'text', left: 'center', top: '51%', style: { text: fmtInt(total), fill: '#1b2430', fontSize: 15, fontWeight: 600, align: 'center' } },
    ],
  }
}

/** 按后端返回的 chart 规格选型，供问答与看板复用 */
export function optionFromSpec(spec: { type: string; labels: string[]; series: { data: number[] }[]; unit: string }): EChartsOption {
  const labels = spec.labels || []
  const data = spec.series?.[0]?.data || []
  if (spec.type === 'line') return lineOption(labels, data, spec.unit)
  if (spec.type === 'pie') return donutOption(labels, data, spec.unit)
  return barOption(labels, data, spec.unit)
}
