import { Children, useEffect, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent, ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import { sendMessageStream, stopAgent } from './api';
import type { GuideMessage, GuideSession, Language, StreamError, WorkSource } from './types';
import styles from './App.module.css';
import { guideCollection, guideParentOrigin, guideStorageKey, readableSourceUrl } from './guideContext';

const MAX_INPUT = 1600;
const params = new URLSearchParams(window.location.search);
const site = params.get('site') === 'p4' ? 'p4' : 'hefa';
const collection = guideCollection(window.location.search);
const STORAGE_KEY = guideStorageKey(collection);
const embedded = params.get('embed') === '1';
const mode = params.get('mode') === 'extract' ? 'extract' : 'model';

const copy = {
  zh: {
    brand: site === 'p4' ? 'P4 剧场' : '何发 HE FA', guide: '作品导览',
    title: '从一个问题，走近作品。',
    description: '依据官网公开资料，提供简短回答与原文出处。文字导览不代表观片体验。',
    prompts: ['何发与人类投降派是什么关系？', '第一次看 P4，从哪里开始？', '《茧房》和《天台上的嚎叫者》有什么不同？', '有哪些公开的装置作品？'],
    suggestions: '可以从这里开始', user: '你', assistant: '导览', sources: '原文出处', read: '阅读原文',
    question: '写下你的问题', placeholder: '问一部作品，也可以接着追问…',
    send: '提问', stop: '停止', stopping: '正在停止…', reset: '重新开始', retry: '重试',
    working: '正在查阅公开资料…', ready: '回答已完成。', excerpt: '原文摘录',
    stopped: '已停止。当前文字可能不完整。', stopUnconfirmed: '已停止显示，服务器取消尚未确认。',
    followup: '接着问', privacy: '仅在本次浏览会话中保留最近 6 条对话。', keyboard: 'Enter 发送 · Shift + Enter 换行',
    unavailable: '暂时无法完成回答，请稍后重试。你也可以阅读下方原文。', interrupted: '连接中断，回答可能不完整。请重试。',
    sourcePublic: '公开资料', sourceFilm: '影像', sourceInstallation: '装置',
  },
  en: {
    brand: site === 'p4' ? 'P4 THEATER' : 'HE FA', guide: 'Works guide', title: 'Begin with a question.',
    description: 'Brief answers drawn from public website materials, with links to the original sources. A text guide cannot replace watching the work.',
    prompts: ['How are He Fa and P4 Theater connected?', 'Where should I start with P4?', 'How do Cocoon and The Rooftop Howler differ?', 'Which installation works are publicly documented?'],
    suggestions: 'A few places to begin', user: 'You', assistant: 'Guide', sources: 'Original sources', read: 'Read the source',
    question: 'Your question', placeholder: 'Ask about a work, or follow up…',
    send: 'Ask', stop: 'Stop', stopping: 'Stopping…', reset: 'Start again', retry: 'Retry',
    working: 'Reading public materials…', ready: 'The answer is ready.', excerpt: 'Source excerpt',
    stopped: 'Stopped. The text may be incomplete.', stopUnconfirmed: 'Display stopped. Server cancellation is not yet confirmed.',
    followup: 'Ask a follow-up', privacy: 'Only the latest 6 messages are kept for this browsing session.', keyboard: 'Enter to send · Shift + Enter for a new line',
    unavailable: 'The answer is temporarily unavailable. Please retry, or read the sources below.', interrupted: 'The connection ended before the answer was complete. Please retry.',
    sourcePublic: 'Public material', sourceFilm: 'Film', sourceInstallation: 'Installation',
  },
};

function newSession(): GuideSession {
  return { conversationId: crypto.randomUUID(), userId: crypto.randomUUID(), site, messages: [] };
}

function readSession(): GuideSession {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null') as GuideSession | null;
    if (!saved || saved.site !== site || typeof saved.conversationId !== 'string' || typeof saved.userId !== 'string' || !Array.isArray(saved.messages)) return newSession();
    const messages = saved.messages.filter(message => message && typeof message.id === 'string' && (message.role === 'user' || message.role === 'assistant') && typeof message.content === 'string').slice(-6).map(message => ({
      ...message, sources: Array.isArray(message.sources) ? message.sources : [], status: message.status === 'streaming' ? 'stopped' as const : message.status,
    }));
    return { ...saved, messages };
  } catch { return newSession(); }
}

function sourceLabel(source: WorkSource, language: Language): string {
  const t = copy[language];
  if (['film', 'video', '电影', '影像'].includes(source.kind.toLowerCase())) return t.sourceFilm;
  if (['installation', '装置'].includes(source.kind.toLowerCase())) return t.sourceInstallation;
  return t.sourcePublic;
}

function citeSources(children: ReactNode, sources: WorkSource[], language: Language): ReactNode {
  return Children.map(children, child => {
    if (typeof child !== 'string') return child;
    return child.split(/(\[E\d+\])/g).map((part, index) => {
      if (!/^\[E\d+\]$/.test(part)) return part;
      const source = sources.find(item => item.id === part.slice(1, -1));
      const url = source && readableSourceUrl(source.url);
      return url ? <a key={index} className={styles.citation} href={url} target="_blank" rel="noopener noreferrer" aria-label={`${part} · ${copy[language].read} · ${source.title}`}>{part}</a> : part;
    });
  });
}

function Sources({ sources, language }: { sources: WorkSource[]; language: Language }) {
  const t = copy[language];
  if (!sources.length) return null;
  return <div className={styles.sources}>
    <p className={styles.sourcesLabel}>{t.sources}<span>{sources.length}</span></p>
    <div className={styles.sourceList}>{sources.map((source, index) => {
      const url = readableSourceUrl(source.url);
      const title = <><span className={styles.sourceNumber}>{source.id}</span><span>{source.title}</span>{url && <span aria-hidden="true" className={styles.externalArrow}>↗</span>}</>;
      return <article className={styles.source} key={`${source.id}-${index}`}>
        <p className={styles.sourceTitle}>{url ? <a href={url} target="_blank" rel="noopener noreferrer" aria-label={`${source.title} · ${t.read}`}>{title}</a> : <span className={styles.sourceTitleText}>{title}</span>}</p>
        <p className={styles.sourceMeta}>{sourceLabel(source, language)}<span aria-hidden="true"> / </span>{url ? new URL(url).hostname : source.site}</p>
        {source.excerpt && <p className={styles.sourceExcerpt}>{source.excerpt}</p>}
      </article>;
    })}</div>
  </div>;
}

export default function App() {
  const [language, setLanguage] = useState<Language>(params.get('lang') === 'en' ? 'en' : 'zh');
  const [session, setSession] = useState<GuideSession>(readSession);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [stopping, setStopping] = useState(false);
  const sessionRef = useRef(session);
  const controllerRef = useRef<AbortController | null>(null);
  const responseIdRef = useRef('');
  const messagesRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const t = copy[language];

  function updateSession(updater: (previous: GuideSession) => GuideSession) {
    const next = updater(sessionRef.current);
    sessionRef.current = next;
    setSession(next);
  }

  useEffect(() => {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ ...session, messages: session.messages.slice(-6) })); } catch { /* Storage is optional. */ }
  }, [session]);

  useEffect(() => {
    document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
    document.title = `${t.brand} · ${t.guide}`;
    const query = new URLSearchParams(window.location.search);
    query.set('lang', language);
    window.history.replaceState(null, '', `${window.location.pathname}?${query.toString()}${window.location.hash}`);
  }, [language, t.brand, t.guide]);

  useEffect(() => {
    const element = messagesRef.current;
    if (element && autoScrollRef.current) element.scrollTop = element.scrollHeight;
  }, [session.messages, loading]);

  useEffect(() => {
    const leave = () => {
      if (!controllerRef.current) return;
      controllerRef.current.abort();
      controllerRef.current = null;
      const active = sessionRef.current;
      void stopAgent(active.conversationId, active.userId, true);
    };
    window.addEventListener('pagehide', leave);
    return () => { window.removeEventListener('pagehide', leave); leave(); };
  }, []);

  useEffect(() => {
    if (!embedded || window.parent === window) return;
    const parentOrigin = guideParentOrigin(document.referrer, window.location.hostname);
    if (!parentOrigin) return;
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') window.parent.postMessage({ type: 'works-guide-close' }, parentOrigin);
    };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, []);

  function updateResponse(id: string, updater: (message: GuideMessage) => GuideMessage) {
    updateSession(previous => ({ ...previous, messages: previous.messages.map(message => message.id === id ? updater(message) : message) }));
  }

  function finish(id: string) {
    if (responseIdRef.current !== id) return;
    controllerRef.current = null;
    setLoading(false);
  }

  function sendQuestion(question: string, retry = false) {
    const trimmed = question.trim();
    if (!trimmed || trimmed.length > MAX_INPUT || controllerRef.current || stopping) return;
    let previous = sessionRef.current.messages;
    if (retry) previous = previous.slice(0, -2);
    const history = previous.filter(message => message.content && (message.role === 'user' || message.status === 'complete')).slice(-6).map(({ role, content }) => ({ role, content }));
    const user: GuideMessage = { id: crypto.randomUUID(), role: 'user', content: trimmed, sources: [], status: 'complete' };
    const response: GuideMessage = { id: crypto.randomUUID(), role: 'assistant', content: '', sources: [], status: 'streaming' };
    responseIdRef.current = response.id;
    autoScrollRef.current = true;
    updateSession(current => ({ ...current, messages: [...previous, user, response].slice(-6) }));
    setInput(''); setLoading(true);
    const active = sessionRef.current;
    controllerRef.current = sendMessageStream({ message: trimmed, conversationId: active.conversationId, userId: active.userId, language, site, collection, history, mode }, {
      onTextDelta(delta) { updateResponse(response.id, message => ({ ...message, content: message.content + delta })); },
      onSources(sources) { updateResponse(response.id, message => ({ ...message, sources })); },
      onAnswerMeta(answerMode) { updateResponse(response.id, message => ({ ...message, mode: answerMode })); },
      onDone(stopped) { updateResponse(response.id, message => ({ ...message, status: stopped ? 'stopped' : 'complete' })); finish(response.id); },
      onError(error) { updateResponse(response.id, message => ({ ...message, status: 'error', error })); finish(response.id); },
    });
  }

  async function stop() {
    const id = responseIdRef.current;
    const active = sessionRef.current;
    setStopping(true);
    controllerRef.current?.abort(); controllerRef.current = null; setLoading(false);
    updateResponse(id, message => ({ ...message, status: 'stopped' }));
    const confirmed = await stopAgent(active.conversationId, active.userId);
    if (!confirmed) updateResponse(id, message => ({ ...message, stopUnconfirmed: true }));
    setStopping(false);
  }

  function reset() {
    if (loading || stopping) return;
    const fresh = newSession(); sessionRef.current = fresh; setSession(fresh); setInput(''); responseIdRef.current = '';
  }
  function submit(event: FormEvent) { event.preventDefault(); sendQuestion(input); }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) { event.preventDefault(); sendQuestion(input); }
  }
  function errorText(error: StreamError | undefined) {
    if (error?.code === 'connection_closed' || error?.code === 'network_error') return t.interrupted;
    if (error?.code.startsWith('http_')) return t.unavailable;
    return error?.message.trim().slice(0, 240) || t.unavailable;
  }
  const lastUser = [...session.messages].reverse().find(message => message.role === 'user');
  const busy = loading || stopping;
  const hasMessages = session.messages.length > 0;
  const lastMessage = session.messages[session.messages.length - 1];
  const announcement = loading ? t.working : stopping ? t.stopping : lastMessage?.status === 'stopped' ? t.stopped : lastMessage?.role === 'assistant' && lastMessage.status === 'complete' ? t.ready : '';

  return <main className={`${styles.shell} ${embedded ? styles.embedded : ''}`}><div className={styles.guide}>
    <header className={styles.header}>
      <div className={styles.identity}><span className={styles.wordmark}>{t.brand}</span><span className={styles.guideLabel}>{t.guide}</span></div>
      <div className={styles.language} aria-label={language === 'zh' ? '语言' : 'Language'}><button type="button" aria-pressed={language === 'zh'} onClick={() => setLanguage('zh')}>中文</button><span aria-hidden="true">/</span><button type="button" aria-pressed={language === 'en'} onClick={() => setLanguage('en')}>EN</button></div>
    </header>
    <section className={`${styles.intro} ${hasMessages ? styles.introCompact : ''}`} aria-labelledby="guide-title"><h1 id="guide-title">{t.title}</h1><p>{t.description}</p></section>
    {!hasMessages && <section className={styles.suggestions} aria-labelledby="suggestions-title"><h2 id="suggestions-title">{t.suggestions}</h2><div className={styles.promptList}>{t.prompts.map((prompt, index) => <button key={index} type="button" onClick={() => sendQuestion(prompt)} disabled={busy}><span>{prompt}</span><span className={styles.promptArrow} aria-hidden="true">↗</span></button>)}</div></section>}
    {hasMessages && <div className={styles.conversationHeader}><p>{t.followup}</p><button className={styles.textButton} onClick={reset} disabled={busy} type="button">{t.reset}<span aria-hidden="true"> ↺</span></button></div>}
    {hasMessages && <section aria-label={language === 'zh' ? '导览对话' : 'Guide conversation'}><div className={styles.messages} ref={messagesRef} onScroll={event => { const element = event.currentTarget; autoScrollRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80; }}>
      {session.messages.map((message, index) => <article key={message.id} className={`${styles.message} ${message.role === 'user' ? styles.userMessage : styles.assistantMessage}`} aria-label={message.role === 'user' ? t.user : t.assistant}>
        <div className={styles.messageLabel}><span>{message.role === 'user' ? t.user : t.assistant}</span>{message.mode === 'extract' && <span className={styles.excerptLabel}>{t.excerpt}</span>}</div>
        {message.role === 'user' ? <p className={styles.userText}>{message.content}</p> : <>
          {message.content ? <div className={styles.answer}><ReactMarkdown components={{
            a: ({ children }) => <span>{children}</span>,
            img: ({ alt }) => <span>{alt || ''}</span>,
            p: ({ children }) => <p>{citeSources(children, message.sources, language)}</p>,
            li: ({ children }) => <li>{citeSources(children, message.sources, language)}</li>,
          }}>{message.content}</ReactMarkdown></div> : message.status === 'streaming' ? <p className={styles.working}>{t.working}</p> : null}
          <Sources sources={message.sources} language={language} />
          {message.status === 'stopped' && <p className={styles.status}>{message.stopUnconfirmed ? t.stopUnconfirmed : t.stopped}</p>}
          {message.status === 'error' && <p role="alert" className={styles.error}>{errorText(message.error)}</p>}
          {['stopped', 'error'].includes(message.status) && index === session.messages.length - 1 && lastUser && message.error?.retryable !== false && <button className={styles.retryButton} type="button" onClick={() => sendQuestion(lastUser.content, true)} disabled={busy}>{t.retry}<span aria-hidden="true"> ↗</span></button>}
        </>}
      </article>)}
    </div></section>}
    <form className={styles.composer} onSubmit={submit}>
      <label className={styles.srOnly} htmlFor="guide-question">{t.question}</label>
      <textarea id="guide-question" value={input} maxLength={MAX_INPUT} onChange={event => setInput(event.target.value)} onKeyDown={keyDown} rows={2} placeholder={t.placeholder} disabled={busy} aria-describedby="input-note" />
      <div className={styles.composerBottom}><span id="input-note" className={styles.inputNote}>{input.length > 1400 ? `${input.length} / ${MAX_INPUT}` : t.keyboard}</span>{loading ? <button className={styles.stopButton} type="button" onClick={() => void stop()}>{t.stop}<span className={styles.stopSquare} aria-hidden="true" /></button> : <button className={styles.sendButton} type="submit" disabled={!input.trim() || busy}>{stopping ? t.stopping : t.send}<span aria-hidden="true"> ↗</span></button>}</div>
    </form>
    <footer className={styles.footer}><p>{t.privacy}</p>{!hasMessages && <button className={styles.textButton} type="button" onClick={reset}>{t.reset}</button>}</footer>
    <div className={styles.srOnly} role="status" aria-live="polite">{announcement}</div>
  </div></main>;
}
