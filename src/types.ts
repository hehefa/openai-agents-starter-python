export type Language = 'zh' | 'en';
export type Site = 'hefa' | 'p4';
export type AnswerMode = 'model' | 'extract';
export interface WorkSource { id: string; title: string; url: string; site: string; kind: string; status: string; excerpt: string; }
export interface StreamError { code: string; message: string; retryable: boolean; }
export interface GuideMessage { id: string; role: 'user' | 'assistant'; content: string; sources: WorkSource[]; status: 'streaming' | 'complete' | 'stopped' | 'error'; mode?: AnswerMode; error?: StreamError; stopUnconfirmed?: boolean; }
export interface GuideSession { conversationId: string; userId: string; site: Site; messages: GuideMessage[]; }
export interface ChatRequest { message: string; conversationId: string; userId: string; language: Language; site: Site; collection?: 'classic'; history: Array<{ role: 'user' | 'assistant'; content: string }>; mode: AnswerMode; }
