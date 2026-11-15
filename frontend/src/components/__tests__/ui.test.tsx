import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge, fmtNum } from "../ui";

describe("StatusBadge", () => {
  it.each([
    ["GROUNDED", "Grounded"],
    ["DUE_SOON", "Due soon"],
    ["OVERDUE", "Overdue"],
    ["AIRWORTHY", "Airworthy"],
  ])("shows a text label for %s, never colour alone", (status, label) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("falls back to the raw value for unknown statuses", () => {
    render(<StatusBadge status="SOMETHING" />);
    expect(screen.getByText("SOMETHING")).toBeInTheDocument();
  });
});

describe("fmtNum", () => {
  it("formats decimals from the API and handles empties", () => {
    expect(fmtNum("1234.567")).toBe("1,234.6");
    expect(fmtNum(null)).toBe("—");
  });
});
