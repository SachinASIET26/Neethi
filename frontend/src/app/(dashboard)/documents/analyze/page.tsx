"use client";

import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { createDocumentAnalysisStream } from "@/lib/api";
import type { DocumentAnalysisResponse, PageIndexNode, PageIndexContentBlock } from "@/types";

type Phase = "idle" | "uploading" | "processing" | "querying" | "synthesizing" | "done" | "error";

const PHASE_LABELS: Record<Phase, string> = {
  idle: "",
  uploading: "Submitting document to PageIndex…",
  processing: "Building document tree…",
  querying: "Running retrieval query…",
  synthesizing: "Synthesizing answer…",
  done: "Analysis complete",
  error: "Analysis failed",
};

export default function DocumentAnalyzePage() {
  const [file, setFile] = useState<File | null>(null);
  const [query, setQuery] = useState("Analyze this legal document");
  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [statusMsg, setStatusMsg] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DocumentAnalysisResponse | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  const loading = phase !== "idle" && phase !== "done" && phase !== "error";

  const handleFile = (f: File) => {
    if (!f.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files are supported.");
      return;
    }
    if (f.size > 20 * 1024 * 1024) {
      setError("File too large. Maximum size is 20 MB.");
      return;
    }
    setError(null);
    setResult(null);
    setPhase("idle");
    setFile(f);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) handleFile(dropped);
  };

  const handleSubmit = () => {
    if (!file) return;
    setResult(null);
    setError(null);
    setPhase("uploading");
    setStatusMsg(PHASE_LABELS.uploading);

    const cancel = createDocumentAnalysisStream(
      file,
      query,
      (event, payload) => {
        const p = payload as Record<string, unknown>;

        if (event === "status") {
          const msg = (p.message as string) ?? "";
          setStatusMsg(msg);
          if (msg.includes("tree")) setPhase("processing");
          else if (msg.includes("retrieval")) setPhase("querying");
          else if (msg.includes("ynthesi")) setPhase("synthesizing");
        }

        if (event === "complete") {
          setResult(p as unknown as DocumentAnalysisResponse);
          setPhase("done");
        }

        if (event === "error") {
          setError((p.detail as string) ?? "Analysis failed.");
          setPhase("error");
        }
      },
      (err) => {
        setError(err.message);
        setPhase("error");
      },
    );

    cancelRef.current = cancel;
  };

  const handleCancel = () => {
    cancelRef.current?.();
    setPhase("idle");
    setStatusMsg("");
  };

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Document Analysis</h1>
        <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
          Upload a PDF and ask a question. PageIndex builds a TOC tree then reasons over it — no vectors required.
        </p>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => !loading && inputRef.current?.click()}
        className={[
          "border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center gap-3 transition-colors",
          loading ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
          dragging
            ? "border-primary bg-primary/5"
            : "border-gray-300 dark:border-slate-700 hover:border-primary hover:bg-primary/5",
        ].join(" ")}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
        />
        <span className="material-symbols-outlined text-4xl text-gray-400 dark:text-slate-500">upload_file</span>
        {file ? (
          <div className="text-center">
            <p className="text-sm font-semibold text-gray-800 dark:text-white">{file.name}</p>
            <p className="text-xs text-gray-400 dark:text-slate-500">
              {(file.size / 1024).toFixed(1)} KB{!loading && " — click to replace"}
            </p>
          </div>
        ) : (
          <div className="text-center">
            <p className="text-sm font-medium text-gray-700 dark:text-slate-300">Drop a PDF here or click to browse</p>
            <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">Max 20 MB · PDF only</p>
          </div>
        )}
      </div>

      {/* Query */}
      <div className="space-y-1.5">
        <label className="text-sm font-medium text-gray-700 dark:text-slate-300">Your question / instruction</label>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={loading}
          rows={3}
          className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-900 dark:text-white px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none disabled:opacity-50"
          placeholder="e.g. What are the key precedents cited? Identify all parties and obligations."
        />
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-400">
          <span className="material-symbols-outlined text-[18px] flex-shrink-0 mt-0.5">error</span>
          {error}
        </div>
      )}

      {/* Progress indicator */}
      {loading && (
        <div className="rounded-xl border border-primary/20 bg-primary/5 px-5 py-4 space-y-3">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-[20px] animate-spin">progress_activity</span>
            <span className="text-sm font-medium text-gray-800 dark:text-white">{statusMsg}</span>
          </div>
          <div className="flex gap-2">
            {(["uploading", "processing", "querying", "synthesizing"] as Phase[]).map((p) => (
              <div
                key={p}
                className={[
                  "h-1.5 flex-1 rounded-full transition-all duration-500",
                  phase === p
                    ? "bg-primary animate-pulse"
                    : (["uploading", "processing", "querying", "synthesizing"] as Phase[]).indexOf(p) <
                      (["uploading", "processing", "querying", "synthesizing"] as Phase[]).indexOf(phase)
                    ? "bg-primary"
                    : "bg-gray-200 dark:bg-slate-700",
                ].join(" ")}
              />
            ))}
          </div>
          <button
            onClick={handleCancel}
            className="text-xs text-gray-400 dark:text-slate-500 hover:text-red-500 transition-colors"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Submit button */}
      {!loading && (
        <button
          onClick={handleSubmit}
          disabled={!file}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-primary text-white font-semibold py-2.5 text-sm transition-opacity disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90"
        >
          <span className="material-symbols-outlined text-[18px]">document_search</span>
          Analyse Document
        </button>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4 pt-2">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">Analysis Results</h2>
            <span className="text-xs text-gray-400 dark:text-slate-500">{result.processing_time_ms} ms</span>
          </div>

          {/* Synthesized answer — primary output */}
          <div className="rounded-xl border border-primary/20 bg-white dark:bg-slate-900 overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-primary/10 bg-primary/5">
              <span className="material-symbols-outlined text-[16px] text-primary">psychology</span>
              <span className="text-sm font-semibold text-gray-800 dark:text-white">AI Legal Analysis</span>
              <span className="ml-auto text-[10px] font-mono text-primary/60 bg-primary/10 px-1.5 py-0.5 rounded">
                grounded · no hallucination
              </span>
            </div>
            <div className="px-4 py-4 text-sm text-gray-800 dark:text-slate-200 leading-relaxed [&_h1]:text-base [&_h1]:font-semibold [&_h1]:text-gray-900 [&_h1]:dark:text-white [&_h1]:mt-4 [&_h1]:mb-2 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-gray-900 [&_h2]:dark:text-white [&_h2]:mt-4 [&_h2]:mb-1.5 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-gray-900 [&_h3]:dark:text-white [&_h3]:mt-3 [&_h3]:mb-1 [&_h4]:text-sm [&_h4]:font-medium [&_h4]:text-gray-900 [&_h4]:dark:text-white [&_h4]:mt-2 [&_h4]:mb-1 [&_p]:mb-2 [&_ul]:list-disc [&_ul]:pl-4 [&_ul]:mb-2 [&_ol]:list-decimal [&_ol]:pl-4 [&_ol]:mb-2 [&_li]:mb-0.5 [&_strong]:font-semibold [&_strong]:text-gray-900 [&_strong]:dark:text-white [&_em]:italic [&_code]:font-mono [&_code]:text-xs [&_code]:bg-gray-100 [&_code]:dark:bg-slate-800 [&_code]:px-1 [&_code]:rounded [&_blockquote]:border-l-2 [&_blockquote]:border-primary/40 [&_blockquote]:pl-3 [&_blockquote]:text-gray-600 [&_blockquote]:dark:text-slate-400 [&_blockquote]:italic">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {result.synthesized_answer}
              </ReactMarkdown>
            </div>
          </div>

          {/* Raw source nodes — collapsible citations */}
          {result.retrieved_nodes.length > 0 && (
            <details className="group">
              <summary className="flex items-center gap-2 cursor-pointer list-none select-none py-1">
                <span className="material-symbols-outlined text-[16px] text-gray-400 dark:text-slate-500 group-open:rotate-90 transition-transform">
                  chevron_right
                </span>
                <span className="text-xs font-medium text-gray-500 dark:text-slate-400">
                  Source excerpts ({result.retrieved_nodes.length} node{result.retrieved_nodes.length !== 1 ? "s" : ""})
                </span>
              </summary>
              <div className="mt-3 space-y-3">
                {result.retrieved_nodes.map((node) => (
                  <NodeCard key={node.id} node={node} />
                ))}
              </div>
            </details>
          )}

          {result.retrieved_nodes.length === 0 && (
            <div className="rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 text-center text-sm text-gray-500 dark:text-slate-400">
              No relevant content found for this query.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function NodeCard({ node }: { node: PageIndexNode }) {
  // Flatten array-of-arrays into a single list of content blocks
  const blocks: PageIndexContentBlock[] = node.relevant_contents.flat();

  return (
    <div className="rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-800/50">
        <span className="material-symbols-outlined text-[16px] text-primary">article</span>
        <span className="text-sm font-semibold text-gray-800 dark:text-white flex-1 truncate">{node.title}</span>
        <span className="text-[10px] font-mono text-gray-400 dark:text-slate-500 bg-gray-100 dark:bg-slate-700 px-1.5 py-0.5 rounded">
          node {node.id}
        </span>
      </div>

      {/* Content blocks */}
      <div className="divide-y divide-gray-100 dark:divide-slate-800">
        {blocks.map((rc, i) => (
          <div key={i} className="px-4 py-3 space-y-1.5">
            {rc.section_title && rc.section_title !== node.title && (
              <p className="text-[11px] font-medium text-primary truncate">{rc.section_title}</p>
            )}
            <p className="text-sm text-gray-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">
              {rc.relevant_content}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
