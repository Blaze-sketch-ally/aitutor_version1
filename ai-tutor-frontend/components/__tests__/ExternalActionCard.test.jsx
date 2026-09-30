import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ExternalActionCard from "../ExternalActionCard";

const t = {
  panel: "#111",
  panelBorder: "#222",
  text: "#fff",
  textDim: "#aaa",
  textFaint: "#888",
  input: "#333",
  accent: "#7C5CFC",
};

describe("ExternalActionCard", () => {
  it("renders the service name, message, and action button for an official source", () => {
    render(
      <ExternalActionCard
        t={t}
        data={{
          message: "You can complete this on the official government portal.",
          action: {
            label: "Open Official Portal",
            url: "https://example.gov",
            service: "Government Portal",
            source_type: "official",
          },
        }}
      />
    );

    expect(screen.getByText("Government Portal")).toBeInTheDocument();
    expect(
      screen.getByText("You can complete this on the official government portal.")
    ).toBeInTheDocument();

    const link = screen.getByRole("link", { name: /open official portal/i });
    expect(link).toHaveAttribute("href", "https://example.gov");
    expect(link).toHaveAttribute("target", "_blank");

    expect(screen.getByText("Official")).toBeInTheDocument();
  });

  it("shows an Unverified badge for a non-official source", () => {
    render(
      <ExternalActionCard
        t={t}
        data={{
          message: "This looks related, but could not be fully verified.",
          action: {
            label: "Open Website",
            url: "https://example.com",
            service: "Example Service",
            source_type: "unverified",
          },
        }}
      />
    );

    expect(screen.getByText("Unverified")).toBeInTheDocument();
  });

  it("renders nothing when there is no action", () => {
    const { container } = render(
      <ExternalActionCard t={t} data={{ message: null, action: null }} />
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when data itself is missing", () => {
    const { container } = render(<ExternalActionCard t={t} data={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});
