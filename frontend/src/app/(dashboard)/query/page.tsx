"use client";

import { useState, useRef, useEffect, Suspense, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { C1Component } from "@thesysai/genui-sdk";
import { useAuthStore } from "@/store/auth";
import { useUIStore, LANGUAGES } from "@/store/ui";
import { createQueryStream, translateAPI, voiceAPI } from "@/lib/api";
import { getVerificationColor, getConfidenceColor, cn } from "@/lib/utils";
import type {
  QueryResponse, CitationResult,
  SSEAgentEvent, SSETokenEvent, SSECompleteEvent,
} from "@/types";
import toast from "react-hot-toast";

// ── Types ──────────────────────────────────────────────────────────────
interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  metadata?: Partial<QueryResponse>;
  agents?: string[];
  progress?: number;
  thesysContent?: string;
  thesysLoading?: boolean;
  thesysStreaming?: boolean;
  showThesys?: boolean;
}

const AGENT_DISPLAY: Record<string, { label: string; icon: string }> = {
  QueryAnalyst:        { label: "Classifying query",        icon: "manage_search" },
  RetrievalSpecialist: { label: "Searching legal database", icon: "database" },
  LegalReasoner:       { label: "Applying IRAC analysis",   icon: "gavel" },
  CitationChecker:     { label: "Verifying citations",      icon: "verified" },
  ResponseFormatter:   { label: "Formatting response",      icon: "format_align_left" },
};

// ── Citation Tag ───────────────────────────────────────────────────────
function CitationTag({ citation }: { citation: CitationResult }) {
  const isVerified = citation.verification === "VERIFIED";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-xs font-medium cursor-pointer transition-all citation-tag",
        isVerified
          ? "bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300 border-gray-200 dark:border-slate-700 hover:border-primary hover:text-primary"
          : "bg-red-50 dark:bg-red-900/20 text-red-500 dark:text-red-400 border-red-200 dark:border-red-800/40"
      )}
      title={citation.section_title}
    >
      <span className="material-symbols-outlined text-[12px]">
        {isVerified ? "verified" : "cancel"}
      </span>
      {citation.act_code.split("_")[0]} {citation.section_number}
    </span>
  );
}

// ── Main Query Content ─────────────────────────────────────────────────
function QueryContent() {
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") || "";
  const { user: authUser } = useAuthStore();
  const { selectedLanguage, setLanguage } = useUIStore();

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState(initialQuery);
  const [isStreaming, setIsStreaming] = useState(false);
  const [includePrecedents, setIncludePrecedents] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [showLangPicker, setShowLangPicker] = useState(false);
  const [voiceOverEnabled, setVoiceOverEnabled] = useState(false);
  const [isTTSLoading, setIsTTSLoading] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stopStreamRef = useRef<(() => void) | null>(null);
  const recognitionRef = useRef<ReturnType<typeof Object.create>>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const voiceOverEnabledRef = useRef(false);
  const latestContentRef = useRef<string>("");

  // Keep refs in sync with state so streaming callbacks always read fresh values
  useEffect(() => { voiceOverEnabledRef.current = voiceOverEnabled; }, [voiceOverEnabled]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);
  useEffect(() => {
    if (initialQuery) handleSend(initialQuery);
  }, []); // eslint-disable-line

  // ── Thesys Visual Summary ──────────────────────────────────────────
  const fetchThesysVisual = useCallback(async (msgId: string, content: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId
          ? { ...m, thesysLoading: true, thesysStreaming: true, showThesys: true, thesysContent: "" }
          : m
      )
    );
    try {
      const res = await fetch("/api/thesys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [
            {
              role: "system",
              content:
                "You are a legal information visualiser for Indian citizens. Transform the legal response into a clear, structured, citizen-friendly format using simple language. Use headings, bullet points, numbered steps, and bold key terms. Avoid jargon. Make it easy for a common person to understand their rights and next steps.",
            },
            { role: "user", content },
          ],
        }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        const detail = (errData as { error?: string }).error || `HTTP ${res.status}`;
        throw new Error(detail);
      }
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response stream");
      const decoder = new TextDecoder();
      let accumulated = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        accumulated += decoder.decode(value, { stream: true });
        setMessages((prev) =>
          prev.map((m) => m.id === msgId ? { ...m, thesysContent: accumulated } : m)
        );
      }
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId ? { ...m, thesysLoading: false, thesysStreaming: false } : m
        )
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      toast.error(`Visual summary failed: ${msg}`);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId
            ? { ...m, thesysLoading: false, thesysStreaming: false, showThesys: false }
            : m
        )
      );
    }
  }, []);

  // ── Send Handler ───────────────────────────────────────────────────
  const handleSend = useCallback((queryText?: string) => {
    const q = (queryText || input).trim();
    if (!q || isStreaming) return;

    const msgId = Date.now().toString();
    const assistantId = `${msgId}-ai`;

    latestContentRef.current = "";
    setMessages((prev) => [
      ...prev,
      { id: msgId, role: "user", content: q },
      { id: assistantId, role: "assistant", content: "", isStreaming: true, agents: [], progress: 0 },
    ]);
    setInput("");
    setIsStreaming(true);

    const stop = createQueryStream(
      { query: q, language: selectedLanguage, include_precedents: includePrecedents },
      async (event, payload) => {
        if (event === "agent_start") {
          const p = payload as SSEAgentEvent;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, agents: [...(m.agents || []), p.agent], progress: Math.min((m.progress || 0) + 20, 90) }
                : m
            )
          );
        } else if (event === "token") {
          const p = payload as SSETokenEvent;
          latestContentRef.current += p.text;
          setMessages((prev) =>
            prev.map((m) => m.id === assistantId ? { ...m, content: m.content + p.text } : m)
          );
        } else if (event === "complete") {
          const p = payload as SSECompleteEvent;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, isStreaming: false, metadata: p, progress: 100 } : m
            )
          );
          setIsStreaming(false);

          // Capture the final content from ref (accumulated by token events)
          let ttsContent = latestContentRef.current;

          // Auto-translate response if a non-English language is selected
          if (selectedLanguage !== "en") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: m.content + "\n\n*(Translating…)*" } : m
              )
            );
            try {
              const translated = await translateAPI.translateText({
                text: ttsContent,
                source_language: "en",
                target_language: selectedLanguage,
                domain: "legal",
              });
              ttsContent = translated.translated_text;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: ttsContent }
                    : m
                )
              );
            } catch {
              // remove translating indicator silently on failure
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content.replace("\n\n*(Translating…)*", "") }
                    : m
                )
              );
            }
          }

          // Auto-play TTS if voiceover toggle is on
          if (voiceOverEnabledRef.current && ttsContent) {
            void (async () => {
              const langCode = SARVAM_LANG_MAP[selectedLanguage] || "en-IN";
              const cleanText = ttsContent.replace(/[#*`_\[\]>~]/g, "").trim();
              if (!cleanText) return;
              setIsTTSLoading(true);
              try {
                const blob = await voiceAPI.textToSpeech(cleanText, langCode);
                const url = URL.createObjectURL(blob);
                const audio = new Audio(url);
                audioRef.current = audio;
                setIsPlaying(true);
                audio.onended = () => {
                  setIsPlaying(false);
                  URL.revokeObjectURL(url);
                  audioRef.current = null;
                };
                audio.onerror = () => {
                  setIsPlaying(false);
                  URL.revokeObjectURL(url);
                  audioRef.current = null;
                };
                await audio.play();
              } catch {
                // auto-play TTS failure is non-fatal
              } finally {
                setIsTTSLoading(false);
              }
            })();
          }
        } else if (event === "error") {
          toast.error("An error occurred. Please try again.");
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, isStreaming: false, content: "Sorry, an error occurred. Please try again." }
                : m
            )
          );
          setIsStreaming(false);
        } else if (event === "end") {
          setIsStreaming(false);
        }
      },
      (_err) => {
        toast.error("Streaming unavailable.");
        setIsStreaming(false);
      }
    );
    stopStreamRef.current = stop;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, isStreaming, selectedLanguage, includePrecedents]);

  const handleStop = () => {
    stopStreamRef.current?.();
    setIsStreaming(false);
    setMessages((prev) => prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m)));
  };

  // ── Copy ───────────────────────────────────────────────────────────
  const handleCopy = (content: string) => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(content).then(() => toast.success("Copied to clipboard"));
    } else {
      const ta = document.createElement("textarea");
      ta.value = content;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      toast.success("Copied to clipboard");
    }
  };

  // ── Share ──────────────────────────────────────────────────────────
  const handleShare = async (content: string, query?: string) => {
    const text = query
      ? `Legal Query: ${query}\n\nAnswer: ${content}\n\n— Neethi AI Legal Assistant`
      : content;
    if (navigator.share) {
      try { await navigator.share({ title: "Neethi AI Legal Response", text }); }
      catch { handleCopy(text); }
    } else {
      handleCopy(text);
      toast.success("Copied — paste to share");
    }
  };

  // ── TTS helpers ────────────────────────────────────────────────────
  const SARVAM_LANG_MAP: Record<string, string> = {
    hi: "hi-IN", ta: "ta-IN", te: "te-IN", bn: "bn-IN",
    mr: "mr-IN", gu: "gu-IN", kn: "kn-IN", ml: "ml-IN", pa: "pa-IN", en: "en-IN",
  };

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    window.speechSynthesis?.cancel();
    setIsPlaying(false);
  }, []);

  const handleSpeak = useCallback(async (content: string) => {
    // If already playing, stop it (toggle off)
    if (isPlaying) { stopAudio(); return; }

    const langCode = SARVAM_LANG_MAP[selectedLanguage] || "en-IN";
    const cleanText = content.replace(/[#*`_\[\]>~]/g, "").trim();
    if (!cleanText) return;

    setIsTTSLoading(true);
    try {
      const blob = await voiceAPI.textToSpeech(cleanText, langCode);
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      setIsPlaying(true);
      audio.onended = () => {
        setIsPlaying(false);
        URL.revokeObjectURL(url);
        audioRef.current = null;
      };
      audio.onerror = () => {
        setIsPlaying(false);
        URL.revokeObjectURL(url);
        audioRef.current = null;
        toast.error("Audio playback failed.");
      };
      await audio.play();
    } catch {
      // Fall back to browser TTS
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(cleanText.slice(0, 500));
        utterance.lang = langCode;
        utterance.rate = 0.9;
        utterance.onend = () => setIsPlaying(false);
        window.speechSynthesis.speak(utterance);
        setIsPlaying(true);
        toast("Reading response aloud (browser TTS fallback)", { icon: "🔊" });
      } else {
        toast.error("TTS unavailable. Check Sarvam AI configuration.");
      }
    } finally {
      setIsTTSLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPlaying, selectedLanguage, stopAudio]);

  // ── STT ────────────────────────────────────────────────────────────
  const handleVoiceInput = () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w = window as any;
    const SpeechRecognitionAPI = w.SpeechRecognition || w.webkitSpeechRecognition;

    if (!SpeechRecognitionAPI) {
      toast.error("Voice input not supported. Try Chrome or Edge.");
      return;
    }
    if (isRecording) {
      recognitionRef.current?.stop();
      setIsRecording(false);
      return;
    }
    const recognition = new SpeechRecognitionAPI();
    const langMap: Record<string, string> = {
      hi: "hi-IN", ta: "ta-IN", te: "te-IN", bn: "bn-IN",
      mr: "mr-IN", gu: "gu-IN", kn: "kn-IN", ml: "ml-IN", pa: "pa-IN", en: "en-IN",
    };
    recognition.lang = langMap[selectedLanguage] || "en-IN";
    recognition.interimResults = true;
    recognition.onstart = () => setIsRecording(true);
    recognition.onend = () => setIsRecording(false);
    recognition.onerror = () => { setIsRecording(false); toast.error("Voice failed. Try again."); };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (e: any) => {
      const transcript = Array.from(e.results as ArrayLike<SpeechRecognitionAlternative[]>)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .map((r: any) => r[0].transcript)
        .join("");
      setInput(transcript);
      if (e.results[e.results.length - 1].isFinal) setIsRecording(false);
    };
    recognitionRef.current = recognition;
    recognition.start();
    toast("Listening… speak now", { icon: "🎙️" });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const isEmpty = messages.length === 0;
  const currentLang = LANGUAGES.find((l) => l.code === selectedLanguage) || LANGUAGES[0];
  // Visual Summary available for all roles (optional toggle)
  const showVisualSummaryOption = true;

  const SUGGESTIONS = [
    { icon: "gavel",   q: "What is the punishment for murder under BNS 2023?" },
    { icon: "balance", q: "Explain the difference between IPC 302 and BNS 103." },
    { icon: "policy",  q: "How to file an anticipatory bail under BNSS 482?" },
    { icon: "groups",  q: "What are fundamental rights under the Indian Constitution?" },
  ];

  return (
    <div className="flex flex-col h-full">
      {/* ── Chat Area ─────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-10 flex flex-col gap-6">

          {/* Empty State */}
          {isEmpty && (
            <div className="flex flex-col items-center justify-center py-16 text-center animate-fade-in">
              <div className="w-16 h-16 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mb-5">
                <span className="material-symbols-outlined text-primary text-3xl">gavel</span>
              </div>
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">AI Legal Assistant</h2>
              <p className="text-gray-500 dark:text-slate-400 text-sm max-w-md leading-relaxed">
                Institutional-grade legal research and statutory analysis. Ask about BNS, IPC, BNSS, case law, or get an IRAC analysis.
              </p>

              {authUser && (
                <div className="mt-4 px-4 py-2.5 rounded-xl bg-primary/5 border border-primary/15 flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[18px]">verified_user</span>
                  <span className="text-sm text-gray-700 dark:text-slate-300">
                    <strong className="text-primary capitalize">{authUser.role}</strong> access ·{" "}
                    Language: <strong className="text-primary">{currentLang.label}</strong>
                  </span>
                </div>
              )}

              <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s.q}
                    onClick={() => handleSend(s.q)}
                    className="flex items-start gap-3 p-4 rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0f172a] text-left hover:border-primary/30 hover:bg-primary/5 transition-all group shadow-sm"
                  >
                    <span className="material-symbols-outlined text-primary text-[18px] flex-shrink-0 mt-0.5 group-hover:scale-110 transition-transform">
                      {s.icon}
                    </span>
                    <span className="text-sm text-gray-700 dark:text-slate-300 group-hover:text-gray-900 dark:group-hover:text-white transition-colors">
                      {s.q}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Messages */}
          {messages.map((message, msgIndex) => (
            <div key={message.id} className="animate-fade-in">
              {message.role === "user" ? (
                <div className="flex justify-end">
                  <div className="max-w-[80%] rounded-2xl bg-primary px-5 py-3.5 text-white shadow-sm">
                    <p className="text-sm leading-relaxed">{message.content}</p>
                  </div>
                </div>
              ) : (
                <div className="flex gap-3 sm:gap-4">
                  <div className="flex-shrink-0">
                    <div className="w-9 h-9 rounded-full bg-primary/20 flex items-center justify-center border border-primary/30">
                      <span className="material-symbols-outlined text-primary text-[18px]">smart_toy</span>
                    </div>
                  </div>

                  <div className="flex-1 min-w-0 flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold uppercase tracking-wider text-primary">Neethi AI Response</span>
                      <span className="text-[10px] text-gray-400 dark:text-slate-500">• Legal AI v1.0</span>
                    </div>

                    {/* Agent progress */}
                    {message.isStreaming && (message.agents?.length || 0) > 0 && (
                      <div className="flex flex-col gap-2 p-4 bg-gray-100 dark:bg-slate-800/30 rounded-xl border border-gray-200 dark:border-slate-800">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-primary agent-active" />
                            <p className="text-gray-700 dark:text-slate-200 text-xs font-medium">
                              {AGENT_DISPLAY[message.agents![message.agents!.length - 1]]?.label || "Processing..."}
                            </p>
                          </div>
                          <span className="text-primary text-xs font-bold font-mono">{message.progress}%</span>
                        </div>
                        <div className="h-1.5 w-full bg-gray-200 dark:bg-slate-800 rounded-full overflow-hidden">
                          <div className="h-full bg-primary rounded-full transition-all duration-500" style={{ width: `${message.progress}%` }} />
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {message.agents?.map((agent, i) => (
                            <span
                              key={agent}
                              className={cn(
                                "text-[10px] px-2 py-0.5 rounded border font-medium",
                                i === message.agents!.length - 1
                                  ? "text-primary border-primary/30 bg-primary/10"
                                  : "text-gray-400 dark:text-slate-500 border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-900"
                              )}
                            >
                              {agent}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* View Toggle: Legal / Visual (all roles, optional) */}
                    {message.content && !message.isStreaming && showVisualSummaryOption && (
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() =>
                            setMessages((prev) =>
                              prev.map((m) => m.id === message.id ? { ...m, showThesys: false } : m)
                            )
                          }
                          className={cn(
                            "px-3 py-1 rounded-full text-xs font-semibold border transition-all",
                            !message.showThesys
                              ? "bg-primary text-white border-primary"
                              : "border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-400 hover:border-primary/40"
                          )}
                        >
                          Legal Response
                        </button>
                        <button
                          onClick={() => {
                            if (!message.thesysContent && !message.thesysLoading) {
                              fetchThesysVisual(message.id, message.content);
                            } else {
                              setMessages((prev) =>
                                prev.map((m) => m.id === message.id ? { ...m, showThesys: true } : m)
                              );
                            }
                          }}
                          className={cn(
                            "flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border transition-all",
                            message.showThesys
                              ? "bg-primary text-white border-primary"
                              : "border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-400 hover:border-primary/40"
                          )}
                        >
                          {message.thesysLoading ? (
                            <>
                              <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
                              Generating...
                            </>
                          ) : (
                            <>
                              <span className="material-symbols-outlined text-[13px]">auto_awesome</span>
                              Visual Summary
                            </>
                          )}
                        </button>
                      </div>
                    )}

                    {/* Response Card */}
                    {message.content && (
                      <div className="rounded-2xl bg-white dark:bg-[#0f172a] border border-gray-200 dark:border-slate-800 p-5 sm:p-6 shadow-sm">
                        {message.showThesys && (message.thesysContent || message.thesysStreaming) ? (
                          <C1Component
                            c1Response={message.thesysContent ?? ""}
                            isStreaming={message.thesysStreaming ?? false}
                          />
                        ) : (
                          <div className="markdown-body text-sm text-gray-800 dark:text-slate-200 leading-relaxed">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                            {message.isStreaming && <span className="streaming-cursor" />}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Citations */}
                    {!message.isStreaming && (message.metadata?.citations?.length ?? 0) > 0 && (
                      <div className="space-y-2">
                        <p className="text-xs text-gray-400 dark:text-slate-500 font-medium uppercase tracking-wider">Citations</p>
                        <div className="flex flex-wrap gap-2">
                          {message.metadata!.citations!.map((c, i) => <CitationTag key={i} citation={c} />)}
                        </div>
                      </div>
                    )}

                    {/* Precedents */}
                    {!message.isStreaming && (message.metadata?.precedents?.length ?? 0) > 0 && (
                      <div className="space-y-2">
                        <p className="text-xs text-gray-400 dark:text-slate-500 font-medium uppercase tracking-wider">Precedents</p>
                        <div className="flex flex-wrap gap-2">
                          {message.metadata!.precedents!.map((p, i) => (
                            <span key={i} className="px-2.5 py-1 rounded-full border border-gray-200 dark:border-slate-700 bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300 text-xs font-medium citation-tag">
                              <span className="material-symbols-outlined text-[12px] mr-1">
                                {p.verification === "VERIFIED" ? "verified" : "cancel"}
                              </span>
                              {p.case_name} ({p.year})
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Metadata + Actions */}
                    {!message.isStreaming && message.metadata && (
                      <div className="flex flex-wrap items-center gap-3">
                        {message.metadata.verification_status && (
                          <span className={cn("text-xs px-2 py-0.5 rounded border font-medium", getVerificationColor(message.metadata.verification_status))}>
                            <span className="material-symbols-outlined text-[12px] mr-1">
                              {message.metadata.verification_status === "VERIFIED" ? "verified" :
                               message.metadata.verification_status === "PARTIALLY_VERIFIED" ? "warning" : "cancel"}
                            </span>
                            {message.metadata.verification_status.replace(/_/g, " ")}
                          </span>
                        )}
                        {message.metadata.confidence && (
                          <span className={cn("text-xs font-medium", getConfidenceColor(message.metadata.confidence))}>
                            {message.metadata.confidence.toUpperCase()} CONFIDENCE
                          </span>
                        )}
                        {message.metadata.processing_time_ms && (
                          <span className="text-xs text-gray-400 dark:text-slate-600">
                            {message.metadata.processing_time_ms}ms
                          </span>
                        )}
                        {message.metadata.cached && (
                          <span className="text-xs text-gray-400 dark:text-slate-600 flex items-center gap-1">
                            <span className="material-symbols-outlined text-[12px]">cached</span>Cached
                          </span>
                        )}

                        {/* Action Buttons */}
                        <div className="flex items-center gap-1 ml-auto">
                          <button
                            onClick={() => handleSpeak(message.content)}
                            disabled={isTTSLoading}
                            className={cn(
                              "p-1.5 rounded-lg transition-colors",
                              isPlaying
                                ? "text-primary bg-primary/10"
                                : "text-gray-400 dark:text-slate-600 hover:text-primary hover:bg-primary/10",
                              isTTSLoading && "opacity-60 pointer-events-none"
                            )}
                            title={isPlaying ? "Stop audio" : isTTSLoading ? "Loading audio…" : "Read aloud (TTS)"}
                          >
                            {isTTSLoading ? (
                              <span className="w-[17px] h-[17px] border-2 border-current border-t-transparent rounded-full animate-spin block" />
                            ) : (
                              <span className="material-symbols-outlined text-[17px]">
                                {isPlaying ? "stop_circle" : "volume_up"}
                              </span>
                            )}
                          </button>
                          <button
                            onClick={() => handleCopy(message.content)}
                            className="p-1.5 rounded-lg text-gray-400 dark:text-slate-600 hover:text-primary hover:bg-primary/10 transition-colors"
                            title="Copy response"
                          >
                            <span className="material-symbols-outlined text-[17px]">content_copy</span>
                          </button>
                          <button
                            onClick={() => {
                              const userMsg = messages[msgIndex - 1];
                              handleShare(
                                message.content,
                                userMsg?.role === "user" ? userMsg.content : undefined
                              );
                            }}
                            className="p-1.5 rounded-lg text-gray-400 dark:text-slate-600 hover:text-primary hover:bg-primary/10 transition-colors"
                            title="Share"
                          >
                            <span className="material-symbols-outlined text-[17px]">share</span>
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Disclaimer */}
                    {!message.isStreaming && message.content && (
                      <p className="text-[10px] text-gray-400 dark:text-slate-600 border-l-2 border-gray-200 dark:border-slate-800 pl-2">
                        AI-assisted legal information only. Consult a qualified legal professional for advice specific to your situation.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* ── Input Area ────────────────────────────────────────────── */}
      <div className="border-t border-gray-200 dark:border-slate-800 bg-white dark:bg-[#020617] px-4 sm:px-6 py-4">
        <div className="max-w-4xl mx-auto flex flex-col gap-3">

          {/* Options Row */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* Language Picker */}
            <div className="relative">
              <button
                onClick={() => setShowLangPicker(!showLangPicker)}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-gray-200 dark:border-slate-700 text-xs font-medium text-gray-600 dark:text-slate-400 hover:border-primary/40 hover:text-primary transition-all"
              >
                <span className="material-symbols-outlined text-[14px]">language</span>
                {currentLang.nativeName}
                <span className="material-symbols-outlined text-[12px]">expand_more</span>
              </button>
              {showLangPicker && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setShowLangPicker(false)} />
                  <div className="absolute bottom-full mb-1 left-0 w-48 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-xl shadow-xl z-20 py-1 animate-fade-in">
                    {LANGUAGES.map((lang) => (
                      <button
                        key={lang.code}
                        onClick={() => { setLanguage(lang.code); setShowLangPicker(false); }}
                        className={cn(
                          "w-full flex items-center justify-between px-3 py-2 text-xs transition-colors",
                          selectedLanguage === lang.code
                            ? "bg-primary/10 text-primary font-semibold"
                            : "text-gray-700 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800"
                        )}
                      >
                        <span>{lang.label}</span>
                        <span className="text-gray-400 dark:text-slate-500">{lang.nativeName}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>

            <button
              onClick={() => setIncludePrecedents(!includePrecedents)}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium transition-all",
                includePrecedents
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-500 hover:text-gray-700 dark:hover:text-slate-400"
              )}
            >
              <span className="material-symbols-outlined text-[14px]">
                {includePrecedents ? "check_circle" : "radio_button_unchecked"}
              </span>
              Include Precedents
            </button>

            {/* Voice-over toggle */}
            <button
              onClick={() => {
                if (voiceOverEnabled) stopAudio();
                setVoiceOverEnabled(!voiceOverEnabled);
              }}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium transition-all",
                voiceOverEnabled
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-500 hover:text-gray-700 dark:hover:text-slate-400"
              )}
              title={voiceOverEnabled ? "Voice-over ON — click to disable" : "Click to enable auto voice-over for responses"}
            >
              <span className="material-symbols-outlined text-[14px]">
                {voiceOverEnabled ? "volume_up" : "volume_off"}
              </span>
              Voice-over
              {isPlaying && <span className="w-2 h-2 rounded-full bg-primary animate-pulse flex-shrink-0" />}
              {isTTSLoading && !isPlaying && (
                <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin flex-shrink-0" />
              )}
            </button>

            {isStreaming && (
              <button
                onClick={handleStop}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-red-300 dark:border-red-500/40 bg-red-50 dark:bg-red-500/10 text-red-500 dark:text-red-400 text-xs font-medium hover:bg-red-100 transition-colors"
              >
                <span className="material-symbols-outlined text-[14px]">stop_circle</span>
                Stop
              </button>
            )}
          </div>

          {/* Textarea */}
          <div className="relative flex items-end gap-2">
            <div className="flex-1 relative">
              <span className="material-symbols-outlined absolute left-3.5 top-3.5 text-gray-400 dark:text-slate-500 text-[20px] pointer-events-none">
                description
              </span>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about BNS, IPC, BNSS, or case law analysis..."
                rows={1}
                disabled={isStreaming}
                className="w-full bg-gray-100 dark:bg-slate-800/50 border border-gray-200 dark:border-slate-700 rounded-xl py-3.5 pl-11 pr-28 resize-none focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 text-gray-800 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500 text-sm transition-all min-h-[52px] max-h-36 disabled:opacity-60"
                style={{ height: "auto" }}
                onInput={(e) => {
                  const t = e.currentTarget;
                  t.style.height = "auto";
                  t.style.height = Math.min(t.scrollHeight, 144) + "px";
                }}
              />
              <div className="absolute right-2 bottom-2 flex items-center gap-1">
                <button
                  type="button"
                  onClick={handleVoiceInput}
                  className={cn(
                    "p-2 rounded-lg transition-colors",
                    isRecording
                      ? "text-red-500 bg-red-50 dark:bg-red-500/10 recording-btn"
                      : "text-gray-400 dark:text-slate-500 hover:text-primary hover:bg-primary/10"
                  )}
                  title={isRecording ? "Stop recording" : "Voice input (STT)"}
                >
                  <span className="material-symbols-outlined text-[20px]">
                    {isRecording ? "mic_off" : "mic"}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => handleSend()}
                  disabled={!input.trim() || isStreaming}
                  className="bg-primary text-white font-bold px-3 py-1.5 rounded-lg flex items-center gap-1.5 hover:bg-amber-600 transition-colors disabled:opacity-40 disabled:pointer-events-none text-xs"
                >
                  SEND
                  <span className="material-symbols-outlined text-[16px]">send</span>
                </button>
              </div>
            </div>
          </div>

          <p className="text-[10px] text-gray-400 dark:text-slate-600 text-center">
            Neethi AI provides legal information, not legal advice. All citations are verified against the Indian legal database.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function QueryPage() {
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <Suspense fallback={
        <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-slate-400">Loading...</div>
      }>
        <QueryContent />
      </Suspense>
    </div>
  );
}
