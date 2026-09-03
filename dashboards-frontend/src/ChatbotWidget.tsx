import React, { useState, useRef, useEffect } from 'react';
import {
  MessageSquare, X, Send, Sparkles, Bot, User, RefreshCw,
  ChevronDown, HelpCircle, Layers, Zap, AlertTriangle, ShieldCheck, Play
} from 'lucide-react';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

const API_BASE =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_DASHBOARDS_API) || '';

const SUGGESTIONS = [
  "🚨 What are the top critical blockers?",
  "🔍 Tell me about Bug #32",
  "🧩 Why is Save / Load at high risk?",
  "📊 What is our defect resolution rate?",
  "⚡ What testing priorities do you recommend?"
];

export function ChatbotWidget({ projectId }: { projectId?: string | null }) {
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: "👋 Hi there! I'm **Bugsy 🐞**, your QA & Game Testing AI companion! Ask me any doubt about our bugs, feature risks, reproduction steps, or testing priorities!",
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    if (isOpen) {
      scrollToBottom();
    }
  }, [messages, isOpen, isStreaming]);

  const handleSend = async (textToSend?: string) => {
    const text = (textToSend || input).trim();
    if (!text || isStreaming) return;

    setInput('');

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: text,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    const botMsgId = (Date.now() + 1).toString();
    const botPlaceholderMsg: ChatMessage = {
      id: botMsgId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    const nextHistory = [...messages, userMsg];
    setMessages([...nextHistory, botPlaceholderMsg]);
    setIsStreaming(true);

    try {
      abortControllerRef.current = new AbortController();

      const response = await fetch(`${API_BASE}/api/bugs/chat-stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          messages: nextHistory.map(m => ({ role: m.role, content: m.content }))
        }),
        signal: abortControllerRef.current.signal
      });

      if (!response.ok || !response.body) {
        throw new Error(`Server returned ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let accumulated = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        accumulated += chunk;

        setMessages(prev =>
          prev.map(m => (m.id === botMsgId ? { ...m, content: accumulated } : m))
        );
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        console.error('Chat stream error:', err);
        setMessages(prev =>
          prev.map(m =>
            m.id === botMsgId
              ? { ...m, content: `⚠️ Oops! I ran into an issue connecting to the AI: ${err.message || 'Unknown error'}` }
              : m
          )
        );
      }
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
    }
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsStreaming(false);
    }
  };

  const clearChat = () => {
    handleStop();
    setMessages([
      {
        id: Date.now().toString(),
        role: 'assistant',
        content: "🧹 Chat cleared! What QA questions can I answer for you today?",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }
    ]);
  };

  const renderFormattedText = (text: string) => {
    const parts = text.split(/(Bug\s*#\d+|#\d+)/gi);
    return parts.map((part, i) => {
      if (/^(Bug\s*#\d+|#\d+)$/i.test(part)) {
        return (
          <span
            key={i}
            className="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded text-xs font-mono font-bold bg-indigo-900/90 text-indigo-200 border border-indigo-600/60 shadow-sm"
          >
            {part}
          </span>
        );
      }
      const boldParts = part.split(/(\*\*[^*]+\*\*)/g);
      return boldParts.map((bp, j) => {
        if (bp.startsWith('**') && bp.endsWith('**')) {
          return <strong key={j} className="text-indigo-200 font-semibold">{bp.slice(2, -2)}</strong>;
        }
        return bp;
      });
    });
  };

  return (
    <>
      {/* Floating Launcher Button at Bottom Left */}
      {!isOpen && (
        <div className="fixed bottom-6 left-6 z-50 flex items-center gap-3">
          <button
            onClick={() => setIsOpen(true)}
            className="group relative flex items-center justify-center w-14 h-14 rounded-full bg-gradient-to-tr from-indigo-600 via-purple-600 to-pink-500 text-white shadow-2xl hover:scale-105 active:scale-95 transition-all duration-300 border-2 border-indigo-400/40 hover:shadow-indigo-500/50 hover:shadow-lg"
            title="Chat with Bugsy AI"
          >
            {/* Mascot Icon */}
            <span className="text-2xl select-none group-hover:rotate-12 transition-transform duration-300">🐞</span>
            
            {/* Pulsing online badge */}
            <span className="absolute top-0.5 right-0.5 flex h-3.5 w-3.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3.5 w-3.5 bg-emerald-500 border-2 border-neutral-900"></span>
            </span>
          </button>

          {/* Cute Greeting Speech Bubble */}
          <div
            onClick={() => setIsOpen(true)}
            className="hidden sm:flex items-center gap-2 bg-neutral-900/95 border border-indigo-500/40 text-neutral-200 text-xs px-3.5 py-2 rounded-xl shadow-xl backdrop-blur-md cursor-pointer hover:border-indigo-400 transition-all group animate-bounce-subtle"
          >
            <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
            <span>Ask <strong>Bugsy</strong> about bugs!</span>
          </div>
        </div>
      )}

      {/* Chat Window Drawer (Bottom Left) */}
      {isOpen && (
        <div className="fixed bottom-6 left-6 z-50 w-[420px] max-w-[calc(100vw-32px)] h-[580px] max-h-[85vh] flex flex-col bg-neutral-900/95 border border-indigo-700/60 rounded-2xl shadow-2xl backdrop-blur-xl overflow-hidden animate-in fade-in slide-in-from-bottom-5 duration-200">
          
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3.5 bg-gradient-to-r from-indigo-950/80 via-purple-950/60 to-neutral-900 border-b border-indigo-800/40">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-full bg-gradient-to-tr from-indigo-600 to-pink-500 flex items-center justify-center text-lg shadow-md border border-indigo-400/40">
                🐞
              </div>
              <div>
                <div className="flex items-center gap-1.5">
                  <h3 className="text-sm font-bold text-white tracking-wide">Bugsy QA Bot</h3>
                  <span className="text-[10px] font-bold bg-indigo-900/80 text-indigo-300 px-1.5 py-0.2 rounded border border-indigo-700/50">AI</span>
                </div>
                <div className="flex items-center gap-1.5 text-[11px] text-emerald-400 font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                  <span>Online • llama3.2</span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1">
              <button
                onClick={clearChat}
                className="p-1.5 text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/60 rounded-lg transition-colors"
                title="Clear conversation"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setIsOpen(false)}
                className="p-1.5 text-neutral-400 hover:text-white hover:bg-neutral-800/60 rounded-lg transition-colors"
                title="Minimize chat"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Messages Scroll Area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3.5 bg-neutral-950/40 text-sm">
            {messages.map((msg) => {
              const isBot = msg.role === 'assistant';
              return (
                <div
                  key={msg.id}
                  className={`flex gap-2.5 ${isBot ? 'items-start' : 'items-end flex-row-reverse'}`}
                >
                  {isBot ? (
                    <div className="w-7 h-7 rounded-full bg-indigo-600/30 border border-indigo-500/40 flex items-center justify-center text-sm shrink-0 shadow-sm">
                      🐞
                    </div>
                  ) : (
                    <div className="w-7 h-7 rounded-full bg-purple-600/30 border border-purple-500/40 flex items-center justify-center text-xs shrink-0 text-purple-300">
                      <User className="w-3.5 h-3.5" />
                    </div>
                  )}

                  <div
                    className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 shadow-sm leading-relaxed whitespace-pre-line ${
                      isBot
                        ? 'bg-neutral-900 border border-indigo-900/50 text-neutral-200'
                        : 'bg-indigo-600 text-white rounded-br-none'
                    }`}
                  >
                    {isBot && !msg.content ? (
                      <div className="flex items-center gap-1.5 py-1 text-indigo-400 animate-pulse">
                        <span className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce"></span>
                        <span className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:0.2s]"></span>
                        <span className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:0.4s]"></span>
                      </div>
                    ) : (
                      renderFormattedText(msg.content)
                    )}
                    <div className="text-[10px] text-neutral-400/70 mt-1 text-right select-none">
                      {msg.timestamp}
                    </div>
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>

          {/* Quick Suggestion Chips */}
          <div className="px-3 py-2 bg-neutral-900/90 border-t border-neutral-800/60 overflow-x-auto flex gap-1.5 no-scrollbar">
            {SUGGESTIONS.map((s, i) => (
              <button
                key={i}
                onClick={() => handleSend(s)}
                disabled={isStreaming}
                className="whitespace-nowrap text-xs bg-neutral-800/80 hover:bg-indigo-950/80 text-neutral-300 hover:text-indigo-200 border border-neutral-700/60 hover:border-indigo-600/60 px-2.5 py-1 rounded-full transition-all disabled:opacity-50"
              >
                {s}
              </button>
            ))}
          </div>

          {/* Input Bar */}
          <div className="p-3 bg-neutral-900 border-t border-indigo-900/40 flex items-center gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Ask Bugsy anything (e.g. Bug #32)..."
              disabled={isStreaming}
              className="flex-1 bg-neutral-950/90 border border-neutral-700/70 focus:border-indigo-500 rounded-xl px-3.5 py-2 text-sm text-neutral-100 placeholder-neutral-500 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 transition-all"
            />
            {isStreaming ? (
              <button
                onClick={handleStop}
                className="p-2 bg-rose-600/80 hover:bg-rose-500 text-white rounded-xl shadow transition-colors"
                title="Stop generating"
              >
                <div className="w-4 h-4 border-2 border-white rounded-sm"></div>
              </button>
            ) : (
              <button
                onClick={() => handleSend()}
                disabled={!input.trim()}
                className="p-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:hover:bg-indigo-600 text-white rounded-xl shadow transition-colors"
                title="Send message"
              >
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      )}
    </>
  );
}
