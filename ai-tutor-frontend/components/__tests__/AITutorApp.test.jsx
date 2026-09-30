import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Stable object, like the real AuthContext (user lives in state): a new
// object per render would re-trigger the app's [user] effect forever.
vi.mock("../../lib/AuthContext", () => {
  const auth = {
    user: { id: "u1", email: "student@example.com" },
    loading: false,
    signOut: () => Promise.resolve(),
  };
  return { useAuth: () => auth };
});

vi.mock("../../lib/api", () => ({
  listSessions: vi.fn(),
  getSessionHistory: vi.fn(),
  getPdfs: vi.fn(),
  getSelectedPdfs: vi.fn(),
  deleteSession: vi.fn(),
  saveSelectedPdfs: vi.fn(() => Promise.resolve()),
  createSession: vi.fn(),
  renameSession: vi.fn(),
}));

import * as api from "../../lib/api";
import AITutorApp from "../AITutorApp";

let mobile = false;

beforeEach(() => {
  vi.clearAllMocks();
  mobile = false;
  window.matchMedia = vi.fn(() => ({
    matches: mobile,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  Element.prototype.scrollTo = vi.fn();

  api.listSessions.mockResolvedValue([{ session_id: "s1", title: "TCP chat" }]);
  api.getSessionHistory.mockResolvedValue([
    { role: "user", content: "What is TCP?" },
    { role: "assistant", content: "TCP is **reliable**." },
  ]);
  api.getPdfs.mockResolvedValue([{ name: "tcp_notes.pdf" }]);
  api.getSelectedPdfs.mockResolvedValue(["tcp_notes.pdf"]);
});

describe("saved chat loading", () => {
  it("loads history and PDF selection normally", async () => {
    render(<AITutorApp />);

    expect(await screen.findByText("What is TCP?")).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a failed load shows a retryable error instead of an empty chat", async () => {
    api.getSessionHistory.mockRejectedValueOnce(new Error("503"));
    api.getPdfs.mockRejectedValueOnce(new Error("503"));

    render(<AITutorApp />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load your saved chat");
    expect(alert).toHaveTextContent("Nothing has been deleted");
    // Not the "no data" states:
    expect(screen.queryByText(/Create a new chat to get started/)).toBeNull();
    expect(screen.queryByText(/None yet/)).toBeNull();
    expect(screen.getByText(/Couldn't load this chat's PDFs/)).toBeInTheDocument();
    // Can't send until the chat (and its PDF selection) has loaded.
    expect(screen.getByRole("textbox", { name: "Message" })).toBeDisabled();

    // Retry succeeds -> saved data returns, error disappears.
    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));

    expect(await screen.findByText("What is TCP?")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(screen.getByRole("textbox", { name: "Message" })).not.toBeDisabled();
  });

  it("a partial failure keeps the loaded messages and retries only what failed", async () => {
    api.getSelectedPdfs.mockRejectedValueOnce(new Error("503"));

    render(<AITutorApp />);

    // History loaded fine and stays visible next to the error.
    expect(await screen.findByText("What is TCP?")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Showing what was already loaded");
    expect(screen.getByRole("textbox", { name: "Message" })).toBeDisabled();

    const historyCalls = api.getSessionHistory.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));

    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(screen.getByText("What is TCP?")).toBeInTheDocument();
    expect(api.getSessionHistory.mock.calls.length).toBe(historyCalls); // not re-fetched
  });
});

describe("delete confirmation", () => {
  it("asks before deleting and can be cancelled", async () => {
    render(<AITutorApp />);
    await screen.findByText("What is TCP?");

    fireEvent.click(screen.getByRole("button", { name: "Delete chat TCP chat" }));

    expect(screen.getByRole("alertdialog", { name: "Confirm delete" })).toBeInTheDocument();
    expect(api.deleteSession).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(api.deleteSession).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete chat TCP chat" }));
    api.deleteSession.mockResolvedValueOnce({ success: true });
    api.listSessions.mockResolvedValueOnce([]);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(api.deleteSession).toHaveBeenCalledWith("s1"));
  });

  it("icon-only controls have accessible names", async () => {
    render(<AITutorApp />);
    await screen.findByText("What is TCP?");

    expect(screen.getByRole("button", { name: "Rename chat TCP chat" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete chat TCP chat" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Toggle theme" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send message" })).toBeInTheDocument();
  });
});

describe("mobile layout", () => {
  it("uses a closed drawer with a menu button below 768px", async () => {
    mobile = true;
    render(<AITutorApp />);
    await screen.findByText("What is TCP?");

    const nav = document.getElementById("app-sidebar");
    expect(nav).toHaveAttribute("aria-hidden", "true");
    expect(nav.style.position).toBe("absolute");

    const menu = screen.getByRole("button", { name: "Open menu" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(menu);

    expect(nav).not.toHaveAttribute("aria-hidden");
    expect(screen.getByRole("button", { name: "Close menu" })).toBeInTheDocument();

    // Opening a chat closes the drawer.
    fireEvent.click(screen.getByRole("button", { name: "TCP chat" }));
    expect(nav).toHaveAttribute("aria-hidden", "true");
  });

  it("keeps the fixed sidebar on desktop", async () => {
    render(<AITutorApp />);
    await screen.findByText("What is TCP?");

    const nav = document.getElementById("app-sidebar");
    expect(nav.style.position).toBe("");
    expect(screen.queryByRole("button", { name: "Open menu" })).toBeNull();
  });
});
