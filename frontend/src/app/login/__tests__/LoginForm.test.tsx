import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const login = vi.fn();
const replace = vi.fn();

vi.mock("@/lib/auth", () => ({ useAuth: () => ({ login, user: null, ready: true }) }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(),
}));

import { DEMO_PASSWORD, LoginForm } from "../LoginForm";

describe("LoginForm demo login", () => {
  afterEach(cleanup);
  beforeEach(() => {
    login.mockReset().mockResolvedValue(undefined);
    replace.mockReset();
  });

  it("logs in as the demo planner with one click", async () => {
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: "Try the demo (one click)" }));
    await waitFor(() => expect(login).toHaveBeenCalledWith("planner", DEMO_PASSWORD));
    expect(replace).toHaveBeenCalledWith("/");
  });

  it("offers the other demo roles", async () => {
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: "Technician" }));
    await waitFor(() => expect(login).toHaveBeenCalledWith("tech", DEMO_PASSWORD));
  });
});
