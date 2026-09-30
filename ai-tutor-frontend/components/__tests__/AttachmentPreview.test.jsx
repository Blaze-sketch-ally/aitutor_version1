import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import AttachmentPreview from "../AttachmentPreview";

const t = {
  panel: "#111",
  panelBorder: "#222",
  text: "#fff",
  textDim: "#aaa",
  textFaint: "#888",
  input: "#222",
  accent: "#7C5CFC",
};

describe("AttachmentPreview", () => {
  it("renders nothing when there are no items", () => {
    const { container } = render(<AttachmentPreview t={t} items={[]} onRemove={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders an image chip with a thumbnail and filename", () => {
    render(
      <AttachmentPreview
        t={t}
        items={[{
          id: "1", kind: "image", name: "textbook.png", size: 2048,
          previewUrl: "blob:x", status: "selected",
        }]}
        onRemove={() => {}}
      />
    );

    expect(screen.getByText("textbook.png")).toBeInTheDocument();
    expect(screen.getByAltText("textbook.png")).toHaveAttribute("src", "blob:x");
  });

  it("renders a PDF chip with its filename", () => {
    render(
      <AttachmentPreview
        t={t}
        items={[{ id: "2", kind: "pdf", name: "operating_systems.pdf", status: "ready" }]}
        onRemove={() => {}}
      />
    );

    expect(screen.getByText("operating_systems.pdf")).toBeInTheDocument();
  });

  it("shows the error message for a failed attachment", () => {
    render(
      <AttachmentPreview
        t={t}
        items={[{ id: "3", kind: "image", name: "bad.png", status: "error", error: "Unable to read image." }]}
        onRemove={() => {}}
      />
    );

    expect(screen.getByText("Unable to read image.")).toBeInTheDocument();
  });

  it("shows a processing label while analyzing", () => {
    render(
      <AttachmentPreview
        t={t}
        items={[{ id: "4", kind: "image", name: "a.png", status: "processing" }]}
        onRemove={() => {}}
      />
    );

    expect(screen.getByText("Analyzing...")).toBeInTheDocument();
  });

  it("calls onRemove with the item when its remove button is clicked", () => {
    const onRemove = vi.fn();
    const item = { id: "5", kind: "video", name: "lecture.mp4", size: 1024, status: "selected" };

    render(<AttachmentPreview t={t} items={[item]} onRemove={onRemove} />);
    screen.getByRole("button", { name: /remove lecture.mp4/i }).click();

    expect(onRemove).toHaveBeenCalledWith(item);
  });

  it("renders multiple attachments independently", () => {
    render(
      <AttachmentPreview
        t={t}
        items={[
          { id: "a", kind: "image", name: "one.png", status: "selected" },
          { id: "b", kind: "image", name: "two.png", status: "selected" },
        ]}
        onRemove={() => {}}
      />
    );

    expect(screen.getByText("one.png")).toBeInTheDocument();
    expect(screen.getByText("two.png")).toBeInTheDocument();
  });
});
