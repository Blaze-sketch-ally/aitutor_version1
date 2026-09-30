import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ExternalLink, Copy, Check } from "lucide-react";

function loadScriptOnce(src, globalCheck) {
  return new Promise((resolve) => {
    if (typeof window !== "undefined" && window[globalCheck]) {
      resolve();
      return;
    }
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve());
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    document.body.appendChild(script);
  });
}

function MermaidBlock({ code, t }) {
  const ref = useRef(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadScriptOnce("https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js", "mermaid").then(() => {
      if (cancelled) return;
      window.mermaid.initialize({ startOnLoad: false, theme: "dark" });
      setReady(true);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!ready || !ref.current) return;
    ref.current.removeAttribute("data-processed");
    ref.current.innerHTML = code;
    try {
      window.mermaid.run({ nodes: [ref.current] });
    } catch (e) {
      console.error("Mermaid render error:", e);
    }
  }, [ready, code]);

  return (
    <div style={{
      background: t.input, borderRadius: 12, padding: 14, border: `1px solid ${t.panelBorder}`,
      overflowX: "auto", maxWidth: "100%",
    }}>
      <div className="mermaid" ref={ref} style={{ textAlign: "center" }}>{code}</div>
    </div>
  );
}

function ChartBlock({ chartData, t }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    let chartInstance = null;

    loadScriptOnce("https://cdn.jsdelivr.net/npm/chart.js@4", "Chart").then(() => {
      if (cancelled || !canvasRef.current) return;

      const palette = ["#9B6BFF", "#5FB878", "#E3766E", "#F5C463", "#4FA8E0", "#C97CE0"];
      const chartType = chartData.chart_type || "bar";
      const datasets = (chartData.datasets || []).map((ds, i) => ({
        label: ds.label || `Series ${i + 1}`,
        data: ds.data || [],
        backgroundColor: palette[i % palette.length],
        borderColor: palette[i % palette.length],
        borderWidth: 2,
      }));

      chartInstance = new window.Chart(canvasRef.current, {
        type: chartType,
        data: { labels: chartData.labels || [], datasets },
        options: {
          plugins: {
            title: { display: !!chartData.title, text: chartData.title || "", color: t.text },
            legend: { labels: { color: t.text } },
          },
        },
      });
    });

    return () => {
      cancelled = true;
      if (chartInstance) chartInstance.destroy();
    };
  }, [chartData, t]);

  return (
    <div style={{ background: t.input, borderRadius: 12, padding: 14, border: `1px solid ${t.panelBorder}` }}>
      <canvas ref={canvasRef} />
    </div>
  );
}

function DiagramBlock({ diagram, t }) {
  if (!diagram) return null;

  // backward compatibility: some old saved messages may have a raw
  // mermaid string instead of the {type, content} dict
  if (typeof diagram === "string") return <MermaidBlock code={diagram} t={t} />;

  if (diagram.type === "mermaid") return <MermaidBlock code={diagram.content} t={t} />;
  if (diagram.type === "chart") return <ChartBlock chartData={diagram.content} t={t} />;
  if (diagram.type === "image") {
    return (
      <div>
        <img src={diagram.content} alt={diagram.prompt || "Generated diagram"} style={{ maxWidth: "100%", borderRadius: 12 }} />
        <div style={{ fontSize: 11, color: t.textFaint, marginTop: 6 }}>Generated with Pollinations.ai</div>
      </div>
    );
  }
  return null;
}

// ---------------------------------------------------------------
// Fenced code block with its own Copy Code button — used by the
// Markdown renderer (MessageText, below) for ```lang fences.
// ---------------------------------------------------------------

function CodeBlock({ lang, code, t }) {
  const [copied, setCopied] = useState(false);

  async function handleCopyCode() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      console.error("Copy code failed:", e);
    }
  }

  return (
    <div style={{ margin: "10px 0" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: t.input,
          border: `1px solid ${t.panelBorder}`,
          borderBottom: "none",
          borderRadius: "10px 10px 0 0",
          padding: "6px 10px",
        }}
      >
        <span style={{ fontSize: 11, color: t.textFaint, fontFamily: "monospace" }}>
          {lang || "code"}
        </span>
        <button
          onClick={handleCopyCode}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            fontSize: 11,
            color: t.textFaint,
            background: "transparent",
            border: "none",
            cursor: "pointer",
            padding: "2px 4px",
          }}
          title="Copy code"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>
      <pre
        style={{
          margin: 0,
          padding: 12,
          overflowX: "auto",
          background: "rgba(0,0,0,0.25)",
          border: `1px solid ${t.panelBorder}`,
          borderRadius: "0 0 10px 10px",
          fontSize: 12.5,
          fontFamily: "'Fira Code',Consolas,monospace",
          color: t.text,
          lineHeight: 1.5,
        }}
      >
        <code>{code}</code>
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------
// Markdown rendering for assistant text (react-markdown + GFM tables,
// strikethrough, task lists). Safety: no rehype-raw — raw HTML in the
// model output is dropped (skipHtml), and react-markdown's default URL
// transform strips javascript:/data: links. Fenced code keeps the
// CodeBlock above (copy button); tables get their own horizontal
// scroller so a wide table never widens the page. Works the same for a
// message still streaming (an unterminated fence renders as an
// in-progress code block) and for one restored from history.
// ---------------------------------------------------------------

function codeText(children) {
  return String(Array.isArray(children) ? children.join("") : children ?? "").replace(/\n$/, "");
}

function markdownComponents(t) {
  const heading = (Tag, size) => ({ node, ...props }) => (
    <Tag style={{
      fontFamily: "'Space Grotesk',sans-serif", fontWeight: 700, fontSize: size,
      color: t.text, margin: "14px 0 6px", lineHeight: 1.35,
    }} {...props} />
  );
  // Cells never split words ("Reliabilit|y"): a wide table scrolls inside
  // its own .md-table-scroll wrapper instead of squeezing columns.
  const cell = {
    border: `1px solid ${t.panelBorder}`, padding: "6px 10px", textAlign: "left", verticalAlign: "top",
    overflowWrap: "normal", wordBreak: "normal", minWidth: 72,
  };

  return {
    h1: heading("h1", 18), h2: heading("h2", 16.5), h3: heading("h3", 15),
    h4: heading("h4", 14), h5: heading("h5", 13.5), h6: heading("h6", 13.5),
    p: ({ node, ...props }) => <p style={{ margin: "0 0 10px" }} {...props} />,
    ul: ({ node, ...props }) => <ul style={{ margin: "0 0 10px", paddingLeft: 22 }} {...props} />,
    ol: ({ node, ...props }) => <ol style={{ margin: "0 0 10px", paddingLeft: 22 }} {...props} />,
    li: ({ node, ...props }) => <li style={{ margin: "3px 0" }} {...props} />,
    blockquote: ({ node, ...props }) => (
      <blockquote style={{
        margin: "0 0 10px", padding: "4px 12px", borderLeft: `3px solid ${t.accent}`,
        color: t.textDim, background: t.input, borderRadius: "0 8px 8px 0",
      }} {...props} />
    ),
    hr: () => <hr style={{ border: "none", borderTop: `1px solid ${t.panelBorder}`, margin: "14px 0" }} />,
    a: ({ node, ...props }) => (
      <a {...props} target="_blank" rel="noopener noreferrer" style={{ color: t.accent, wordBreak: "break-word" }} />
    ),
    table: ({ node, ...props }) => (
      <div className="md-table-scroll" style={{ overflowX: "auto", maxWidth: "100%", margin: "4px 0 12px" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12.5, minWidth: "100%" }} {...props} />
      </div>
    ),
    th: ({ node, ...props }) => <th style={{ ...cell, background: t.input, fontWeight: 600 }} {...props} />,
    td: ({ node, ...props }) => <td style={cell} {...props} />,
    // Fenced code: <pre><code class="language-x">…</code></pre>
    pre: ({ node, children }) => {
      const child = Array.isArray(children) ? children[0] : children;
      const lang = /language-([\w+-]+)/.exec(child?.props?.className || "")?.[1] || "";
      return <CodeBlock lang={lang} code={codeText(child?.props?.children)} t={t} />;
    },
    // Inline code (fenced code is handled by `pre` above).
    code: ({ node, className, children, ...props }) => (
      <code className={className} style={{
        fontFamily: "'Fira Code',Consolas,monospace", fontSize: "0.92em",
        background: t.input, padding: "1px 5px", borderRadius: 5,
      }} {...props}>{children}</code>
    ),
  };
}

// The models often emit a section title as bold-wrapped heading syntax on
// its own line ("**# Key Concepts**"), which Markdown correctly reads as
// bold text starting with a literal "#". Presentation-only fix: a line
// that is ONLY that pattern becomes a real heading.
const BOLD_HEADING_LINE_RE = /^[ \t]*\*\*(#{1,6})[ \t]+(.+?)\*\*[ \t]*$/gm;

export function normalizeMarkdown(text) {
  return text.replace(BOLD_HEADING_LINE_RE, "$1 $2");
}

export function MessageText({ content, t, streaming }) {
  const components = useMemo(() => markdownComponents(t), [t]);

  if (!content) return null;

  return (
    <div className="md-body" style={{ overflowWrap: "anywhere", minWidth: 0 }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={components}>
        {normalizeMarkdown(content)}
      </ReactMarkdown>
      {streaming && <span style={{ opacity: 0.6 }}>▌</span>}
    </div>
  );
}

function formatCount(n) {
  if (n === null || n === undefined) return null;
  const num = Number(n);
  return Number.isNaN(num) ? String(n) : num.toLocaleString();
}

function VideoCard({ video, t }) {
  const segment = video.study_segment;
  return (
    <div style={{ padding: 14, borderRadius: 12, border: `1px solid ${t.panelBorder}`, background: t.panel, marginBottom: 10 }}>
      <div style={{ fontWeight: 600, fontSize: 13.5, color: t.text, marginBottom: 4 }}>{video.title || "Untitled Video"}</div>
      {video.channel && <div style={{ fontSize: 11.5, color: t.textFaint, marginBottom: 6 }}>Channel: {video.channel}</div>}
      {video.description && (
        <div style={{ fontSize: 12.5, color: t.textDim, marginBottom: 6 }}>
          {video.description.replace(/\n/g, " ").slice(0, 160)}
          {video.description.length > 160 ? "…" : ""}
        </div>
      )}
      <div style={{ fontSize: 11.5, color: t.textFaint, marginBottom: 8 }}>
        {[
          formatCount(video.views) && `${formatCount(video.views)} views`,
          formatCount(video.likes) && `${formatCount(video.likes)} likes`,
          video.duration_minutes != null && `${video.duration_minutes} min`,
        ].filter(Boolean).join(" · ")}
      </div>
      {video.url && (
        <a href={video.url} target="_blank" rel="noreferrer" style={{
          display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: t.accent,
          textDecoration: "none", fontWeight: 600,
        }}>
          Watch video <ExternalLink size={12} />
        </a>
      )}
      {segment && (
        <div style={{ marginTop: 8, fontSize: 12, color: t.textDim }}>
          Watch <strong>{segment.start_label} – {segment.end_label}</strong> for the relevant part.
          {video.url_at_timestamp && (
            <>
              {" "}
              <a href={video.url_at_timestamp} target="_blank" rel="noreferrer" style={{ color: t.accent }}>
                Jump to {segment.start_label}
              </a>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function PaperCard({ paper, t }) {
  return (
    <div style={{ padding: 14, borderRadius: 12, border: `1px solid ${t.panelBorder}`, background: t.panel, marginBottom: 10 }}>
      <div style={{ fontWeight: 600, fontSize: 13.5, color: t.text, marginBottom: 4 }}>{paper.title || "Untitled Paper"}</div>
      {paper.authors && <div style={{ fontSize: 11.5, color: t.textFaint, marginBottom: 4 }}>{paper.authors.join(", ")}</div>}
      {paper.published && <div style={{ fontSize: 11.5, color: t.textFaint, marginBottom: 6 }}>Published: {paper.published}</div>}
      {paper.summary && <div style={{ fontSize: 12.5, color: t.textDim, marginBottom: 8 }}>{paper.summary.slice(0, 220)}…</div>}
      {paper.pdf_url && (
        <a href={paper.pdf_url} target="_blank" rel="noreferrer" style={{
          display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: t.accent,
          textDecoration: "none", fontWeight: 600,
        }}>
          Open paper <ExternalLink size={12} />
        </a>
      )}
    </div>
  );
}

function WebResultCard({ result, t }) {
  return (
    <div style={{ padding: 14, borderRadius: 12, border: `1px solid ${t.panelBorder}`, background: t.panel, marginBottom: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span style={{
          fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4,
          padding: "2px 7px", borderRadius: 6, background: t.input, color: t.textDim,
        }}>
          {result.tool === "news" ? "News" : "Web"}
        </span>
        {result.domain && <span style={{ fontSize: 11.5, color: t.textFaint }}>{result.domain}</span>}
        {result.published_date && <span style={{ fontSize: 11.5, color: t.textFaint }}>· {result.published_date}</span>}
      </div>
      <div style={{ fontWeight: 600, fontSize: 13.5, color: t.text, marginBottom: 6 }}>{result.title || "Untitled"}</div>
      {result.snippet && (
        <div style={{ fontSize: 12.5, color: t.textDim, marginBottom: 8 }}>
          {result.snippet.length > 220 ? `${result.snippet.slice(0, 220)}…` : result.snippet}
        </div>
      )}
      {result.url && (
        <a href={result.url} target="_blank" rel="noreferrer" style={{
          display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: t.accent,
          textDecoration: "none", fontWeight: 600,
        }}>
          Read source <ExternalLink size={12} />
        </a>
      )}
    </div>
  );
}

function SourcesList({ sources, t }) {
  const uniquePdfs = Array.from(new Set(sources.map((s) => s.source || "Unknown PDF"))).sort();
  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
        {uniquePdfs.map((pdf) => (
          <span key={pdf} style={{
            fontSize: 11.5, padding: "4px 9px", borderRadius: 7, background: t.input,
            border: `1px solid ${t.panelBorder}`, color: t.textDim,
          }}>
            {pdf}
          </span>
        ))}
      </div>
      {sources.map((s, i) => (
        <div key={i} style={{ fontSize: 11.5, color: t.textFaint, marginBottom: 3, fontFamily: "monospace" }}>
          {s.source || "Unknown"} — page {s.page ?? "N/A"}, chunk {s.chunk_id ?? "N/A"}
        </div>
      ))}
    </div>
  );
}

const TAB_SPECS = [
  { key: "diagram", label: "Diagram" },
  { key: "videos", label: "Videos" },
  { key: "papers", label: "Papers" },
  { key: "web_sources", label: "Web Results" },
  { key: "sources", label: "Sources" },
];

export function MessageExtras({ message, t }) {
  const available = TAB_SPECS.filter((spec) => {
    const val = message[spec.key];
    return Array.isArray(val) ? val.length > 0 : !!val;
  });

  const [active, setActive] = useState(available[0]?.key);

  if (available.length === 0) return null;

  const currentKey = available.some((s) => s.key === active) ? active : available[0].key;

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", gap: 4, marginBottom: 10, borderBottom: `1px solid ${t.panelBorder}` }}>
        {available.map((spec) => (
          <button
            key={spec.key}
            onClick={() => setActive(spec.key)}
            style={{
              padding: "6px 12px", border: "none", background: "transparent", cursor: "pointer",
              fontSize: 12.5, fontFamily: "Inter,sans-serif", fontWeight: 500,
              color: currentKey === spec.key ? t.accent : t.textDim,
              borderBottom: currentKey === spec.key ? `2px solid ${t.accent}` : "2px solid transparent",
            }}
          >
            {spec.label}
          </button>
        ))}
      </div>

      {currentKey === "diagram" && <DiagramBlock diagram={message.diagram} t={t} />}
      {currentKey === "videos" && (message.videos || []).map((v, i) => <VideoCard key={i} video={v} t={t} />)}
      {currentKey === "papers" && (message.papers || []).map((p, i) => <PaperCard key={i} paper={p} t={t} />)}
      {currentKey === "web_sources" && (message.web_sources || []).map((r, i) => <WebResultCard key={i} result={r} t={t} />)}
      {currentKey === "sources" && <SourcesList sources={message.sources || []} t={t} />}
    </div>
  );
}

export function buildAssistantText(result) {
  let text = "";
  if (result.chat) text += result.chat + "\n\n";
  if (result.answer) text += result.answer + "\n\n";
  if (result.comparison) text += "Comparison\n\n" + result.comparison + "\n\n";
  if (result.notes) text += "Notes\n\n" + result.notes + "\n\n";
  if (result.quiz) text += "Quiz\n\n" + result.quiz + "\n\n";
  if (result.web_research) text += result.web_research + "\n\n";
  if (result.external_action?.message) text += result.external_action.message + "\n\n";
  return text.trim();
}
