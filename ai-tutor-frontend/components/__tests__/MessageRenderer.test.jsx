import { render, screen } from "@testing-library/react";
import { MessageText } from "../MessageRenderer";
import { THEMES } from "../../lib/theme";

const t = THEMES.dark;

function renderMd(content, props = {}) {
  return render(<MessageText content={content} t={t} {...props} />);
}

describe("MessageText Markdown rendering", () => {
  it("renders headings, bold, italic and lists as elements, not raw markers", () => {
    const { container } = renderMd(
      "## Topic Overview\n\n**Bold point** and *italic*\n\n- one\n- two\n\n1. first\n2. second"
    );

    expect(screen.getByRole("heading", { name: "Topic Overview" })).toBeInTheDocument();
    expect(container.querySelector("strong").textContent).toBe("Bold point");
    expect(container.querySelector("em").textContent).toBe("italic");
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    expect(container.textContent).not.toContain("**");
    expect(container.textContent).not.toContain("##");
  });

  it("renders GFM tables as real tables inside a horizontal scroller", () => {
    const { container } = renderMd(
      "| Feature | TCP | UDP |\n|---|---|---|\n| Reliable | Yes | No |"
    );

    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(table.querySelectorAll("th")).toHaveLength(3);
    expect(table.querySelectorAll("td")).toHaveLength(3);
    const scroller = table.parentElement;
    expect(scroller.className).toContain("md-table-scroll");
    expect(scroller.style.overflowX).toBe("auto");
    expect(container.textContent).not.toContain("|---|");
  });

  it("renders blockquotes, inline code, horizontal rules and links", () => {
    const { container } = renderMd(
      "> quoted\n\nUse `cwnd` here.\n\n---\n\n[docs](https://example.com)"
    );

    expect(container.querySelector("blockquote").textContent).toContain("quoted");
    expect(container.querySelector("p code").textContent).toBe("cwnd");
    expect(container.querySelector("hr")).not.toBeNull();
    const link = container.querySelector("a");
    expect(link.getAttribute("href")).toBe("https://example.com");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("renders fenced code with the copy-code block", () => {
    renderMd("```python\nprint('hi')\n```");

    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText("Copy code")).toBeInTheDocument();
    expect(screen.getByText("print('hi')")).toBeInTheDocument();
  });

  it("does not render raw HTML from the model", () => {
    const { container } = renderMd('Hello <img src=x onerror="alert(1)"> <script>alert(2)</script> world');

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });

  it("strips javascript: links", () => {
    const { container } = renderMd("[click](javascript:alert(1))");

    const href = container.querySelector("a")?.getAttribute("href") || "";
    expect(href.toLowerCase()).not.toContain("javascript");
  });

  it("renders partial content while streaming (unterminated fence, cursor)", () => {
    const { container } = renderMd("## Partial\n\n```js\nconst x", { streaming: true });

    expect(screen.getByRole("heading", { name: "Partial" })).toBeInTheDocument();
    expect(screen.getByText("const x")).toBeInTheDocument();
    expect(container.textContent).toContain("▌");
  });

  it("turns bold-wrapped heading lines into real headings", () => {
    const { container } = renderMd("**# Key Concepts**\n\n- a\n\nKeep **# inline** text as-is.");

    expect(screen.getByRole("heading", { name: "Key Concepts" })).toBeInTheDocument();
    expect(container.textContent).not.toContain("# Key");
    // Only whole-line patterns are converted.
    expect(container.querySelector("p strong").textContent).toBe("# inline");
  });

  it("renders nothing for empty content", () => {
    const { container } = renderMd("");
    expect(container.innerHTML).toBe("");
  });
});
