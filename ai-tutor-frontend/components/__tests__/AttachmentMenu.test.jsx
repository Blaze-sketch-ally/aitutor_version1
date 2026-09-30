import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import AttachmentMenu from "../AttachmentMenu";

const t = {
  panel: "#111",
  panelBorder: "#222",
  panelBorderStrong: "#333",
  text: "#fff",
  textDim: "#aaa",
  textFaint: "#888",
  input: "#222",
  accent: "#7C5CFC",
  accentSoft: "#333",
};

function setup(props = {}) {
  const onPickImages = vi.fn();
  const onPickPdf = vi.fn();
  const onPickFile = vi.fn();

  render(
    <AttachmentMenu
      t={t}
      disabled={false}
      onPickImages={onPickImages}
      onPickPdf={onPickPdf}
      onPickFile={onPickFile}
      {...props}
    />
  );

  return { onPickImages, onPickPdf, onPickFile };
}

describe("AttachmentMenu", () => {
  it("renders the + trigger button", () => {
    setup();
    expect(screen.getByRole("button", { name: /add attachment/i })).toBeInTheDocument();
  });

  it("opens the menu on click and shows all three options", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /add attachment/i }));

    expect(screen.getByText("Add photos & images")).toBeInTheDocument();
    expect(screen.getByText("Upload PDF")).toBeInTheDocument();
    expect(screen.getByText("Upload files")).toBeInTheDocument();
  });

  it("closes the menu when Escape is pressed", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /add attachment/i }));
    expect(screen.getByText("Add photos & images")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("Add photos & images")).not.toBeInTheDocument();
  });

  it("closes the menu on outside click", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /add attachment/i }));
    fireEvent.mouseDown(document.body);

    expect(screen.queryByText("Add photos & images")).not.toBeInTheDocument();
  });

  it("clicking 'Add photos & images' triggers the hidden image file input", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /add attachment/i }));

    const clickSpy = vi.spyOn(HTMLInputElement.prototype, "click");
    fireEvent.click(screen.getByText("Add photos & images"));

    expect(clickSpy).toHaveBeenCalled();
    clickSpy.mockRestore();
  });

  it("calls onPickImages with the selected files", () => {
    const { onPickImages } = setup();
    const file = new File(["x"], "a.png", { type: "image/png" });
    const input = document.querySelector('input[accept*="image/png"]');

    fireEvent.change(input, { target: { files: [file] } });

    expect(onPickImages).toHaveBeenCalledWith([file]);
  });

  it("calls onPickPdf with the selected file", () => {
    const { onPickPdf } = setup();
    const file = new File(["x"], "notes.pdf", { type: "application/pdf" });
    const input = document.querySelector('input[accept*="application/pdf"]');

    fireEvent.change(input, { target: { files: [file] } });

    expect(onPickPdf).toHaveBeenCalledWith(file);
  });

  it("calls onPickFile with the selected video/audio file", () => {
    const { onPickFile } = setup();
    const file = new File(["x"], "lecture.mp4", { type: "video/mp4" });
    const input = document.querySelector('input[accept*=".mp4"]');

    fireEvent.change(input, { target: { files: [file] } });

    expect(onPickFile).toHaveBeenCalledWith(file);
  });

  it("disables the trigger button when disabled prop is true", () => {
    setup({ disabled: true });
    expect(screen.getByRole("button", { name: /add attachment/i })).toBeDisabled();
  });
});
