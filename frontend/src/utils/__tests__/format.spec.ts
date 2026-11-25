import { describe, expect, it } from 'vitest'
import { fmt, fmtInt, intentLabel, pct, truncate } from '@/utils/format'

describe('format', () => {
  it('千分位并保留固定小数位', () => {
    expect(fmt(223832)).toBe('223,832.00')
    expect(fmt(0, 0)).toBe('0')
    expect(fmt(null)).toBe('—')
    expect(fmt('abc' as unknown)).toBe('—')
  })

  it('整数格式化', () => {
    expect(fmtInt(52321.4)).toBe('52,321')
  })

  it('百分比带符号且无正负零', () => {
    expect(pct(8.24)).toBe('+8.2%')
    expect(pct(-8.24)).toBe('-8.2%')
    expect(pct(0)).toBe('+0.0%')
    expect(pct(null)).toBe('—')
  })

  it('意图标签映射', () => {
    expect(intentLabel('data')).toBe('取数')
    expect(intentLabel('kb')).toBe('制度口径')
    expect(intentLabel('unknown')).toBe('unknown')
    expect(intentLabel(undefined)).toBe('')
  })

  it('超长文本截断', () => {
    expect(truncate('茂名高速公路机电EPC总承包工程', 8)).toBe('茂名高速公路机电…')
    expect(truncate('短', 8)).toBe('短')
  })
})
