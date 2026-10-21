import type { AnswerMode, ChatRequest, StreamError, WorkSource } from './types';
interface StreamCallbacks { onTextDelta: (delta: string) => void; onSources: (sources: WorkSource[]) => void; onAnswerMeta: (mode: AnswerMode) => void; onDone: (stopped: boolean) => void; onError: (error: StreamError) => void; }
function parseSources(value: unknown): WorkSource[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is WorkSource => !!item && typeof item === 'object' && ['id', 'title', 'url', 'site', 'kind', 'status', 'excerpt'].every(key => typeof item[key] === 'string')).slice(0, 6);
}
export function sendMessageStream(request: ChatRequest, callbacks: StreamCallbacks): AbortController {
  const controller = new AbortController();
  void (async () => {
    let terminal = false;
    const fail = (error: StreamError) => { if (terminal || controller.signal.aborted) return; terminal = true; callbacks.onError(error); };
    const dispatch = (frame: string) => {
      if (terminal || controller.signal.aborted) return;
      let event = '';
      const data: string[] = [];
      for (const line of frame.split('\n')) { if (line.startsWith('event:')) event = line.slice(6).trim(); else if (line.startsWith('data:')) data.push(line.slice(5).trimStart()); }
      if (!data.length) return;
      let parsed: Record<string, unknown>;
      try { parsed = JSON.parse(data.join('\n')) as Record<string, unknown>; } catch { fail({ code: 'invalid_response', message: 'Invalid response', retryable: true }); return; }
      if (!parsed || typeof parsed !== 'object') return;
      if (event === 'text_delta' && typeof parsed.delta === 'string') callbacks.onTextDelta(parsed.delta);
      else if (event === 'sources') callbacks.onSources(parseSources(parsed.sources));
      else if (event === 'answer_meta' && (parsed.mode === 'model' || parsed.mode === 'extract')) callbacks.onAnswerMeta(parsed.mode);
      else if (event === 'error') fail({ code: typeof parsed.code === 'string' ? parsed.code : 'server_error', message: typeof parsed.message === 'string' ? parsed.message : 'The guide is unavailable', retryable: parsed.retryable !== false });
      else if (event === 'done') { terminal = true; callbacks.onDone(parsed.stopped === true); }
    };
    try {
      const response = await fetch('/chat', { method: 'POST', headers: { 'Content-Type': 'application/json', 'makers-conversation-id': request.conversationId }, body: JSON.stringify(request), signal: controller.signal });
      if (!response.ok) { fail({ code: `http_${response.status}`, message: 'The guide is unavailable', retryable: response.status !== 400 && response.status !== 413 }); return; }
      const reader = response.body?.getReader();
      if (!reader) { fail({ code: 'network_error', message: 'Streaming is unavailable', retryable: true }); return; }
      const decoder = new TextDecoder();
      let buffer = '';
      while (!terminal && !controller.signal.aborted) {
        const { value, done } = await reader.read();
        buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
        buffer = buffer.replace(/\r\n/g, '\n');
        let boundary = buffer.indexOf('\n\n');
        while (boundary !== -1 && !terminal) { dispatch(buffer.slice(0, boundary)); buffer = buffer.slice(boundary + 2); boundary = buffer.indexOf('\n\n'); }
        if (done) { if (buffer.trim()) dispatch(buffer); break; }
      }
      if (terminal) await reader.cancel().catch(() => undefined);
      else fail({ code: 'connection_closed', message: 'The connection ended early', retryable: true });
    } catch { fail({ code: 'network_error', message: 'The guide could not be reached', retryable: true }); }
  })();
  return controller;
}
export async function stopAgent(conversationId: string, userId: string, keepalive = false): Promise<boolean> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8000);
  try { const response = await fetch('/chat/stop', { method: 'POST', headers: { 'Content-Type': 'application/json', 'makers-conversation-id': conversationId }, body: JSON.stringify({ conversation_id: conversationId, conversationId, userId }), signal: controller.signal, keepalive }); return response.ok; }
  catch { return false; }
  finally { window.clearTimeout(timeout); }
}
