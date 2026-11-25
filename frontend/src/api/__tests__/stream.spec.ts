import { describe, expect, it, vi, afterEach } from 'vitest'
import { askStream } from '@/api'

/** 构造按给定分片返回的 SSE 响应，模拟服务端逐帧推送 */
function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((c) => controller.enqueue(encoder.encode(c)))
      controller.close()
    },
  })
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

describe('askStream', () => {
  afterEach(() => vi.restoreAllMocks())

  it('按事件类型分发 stage / sql / result', async () => {
    const frames = [
      'event: stage\ndata: {"name":"router","text":"意图识别：自然语言取数"}\n\n',
      'event: sql\ndata: {"chunk":"SELECT * FROM (","done":false}\n\n',
      'event: sql\ndata: {"chunk":"\\nSELECT 1","done":false}\n\n',
      'event: sql\ndata: {"chunk":"","done":true}\n\n',
      'event: result\ndata: {"answer":"完成","intent":"data","latency_ms":9}\n\n',
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(frames)))

    const stages: string[] = []
    const sql: string[] = []
    let answer = ''
    await askStream('U001', '测试', 's1', {
      onStage: (s) => stages.push(s.text),
      onSql: (chunk, done) => {
        if (!done) sql.push(chunk)
      },
      onResult: (p) => (answer = p.answer),
    })

    expect(stages).toEqual(['意图识别：自然语言取数'])
    expect(sql.join('')).toBe('SELECT * FROM (\nSELECT 1')
    expect(answer).toBe('完成')
  })

  it('跨网络分片的消息能被正确拼装', async () => {
    const whole = 'event: result\ndata: {"answer":"跨片","intent":"kb","latency_ms":1}\n\n'
    const frames = [whole.slice(0, 18), whole.slice(18, 40), whole.slice(40)]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(frames)))

    let answer = ''
    await askStream('U001', '制度', 's2', { onResult: (p) => (answer = p.answer) })
    expect(answer).toBe('跨片')
  })

  it('error 事件走 onError 而不是抛异常', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(sseResponse(['event: error\ndata: {"message":"处理超时"}\n\n'])),
    )
    let msg = ''
    await askStream('U001', 'x', 's3', { onError: (m) => (msg = m) })
    expect(msg).toBe('处理超时')
  })
})
