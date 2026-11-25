import { describe, expect, it } from 'vitest'
import { extractHeadings, renderMarkdown } from '@/utils/markdown'

describe('markdown', () => {
  it('渲染标题与加粗', () => {
    const html = renderMarkdown('## 一、经营总览\n本期 **新签合同额** 为 132,005.00 万元。')
    expect(html).toContain('<h2>一、经营总览</h2>')
    expect(html).toContain('<strong>新签合同额</strong>')
  })

  it('渲染表格且数值列右对齐', () => {
    const html = renderMarkdown('| 分公司 | 金额(万元) |\n|---|---|\n| 新能源 | 63,937.00 |')
    expect(html).toContain('<table>')
    expect(html).toContain('<td class="num">63,937.00</td>')
  })

  it('列表与引用块', () => {
    const html = renderMarkdown('> 数据来源：宽表\n\n- 第一条\n- 第二条')
    expect(html).toContain('<blockquote>数据来源：宽表</blockquote>')
    expect(html).toContain('<li>第一条</li>')
  })

  it('转义 HTML，避免注入', () => {
    expect(renderMarkdown('<script>alert(1)</script>')).not.toContain('<script>')
  })

  it('抽取二级标题生成目录', () => {
    const heads = extractHeadings('# 报告\n\n## 一、总览\n正文\n## 二、合同')
    expect(heads).toHaveLength(2)
    expect(heads[1]).toEqual({ id: 'sec-1', title: '二、合同' })
  })
})
