import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";

function Broken(): never {
	throw new Error("cannot read properties of undefined");
}

describe("ErrorBoundary", () => {
	afterEach(() => vi.restoreAllMocks());

	it("shows the page when nothing breaks", () => {
		render(
			<ErrorBoundary>
				<p>the page</p>
			</ErrorBoundary>,
		);
		expect(screen.getByText("the page")).toBeInTheDocument();
	});

	it("shows what went wrong and a reload button instead of a black page", () => {
		vi.spyOn(console, "error").mockImplementation(() => {});
		render(
			<ErrorBoundary>
				<Broken />
			</ErrorBoundary>,
		);
		expect(screen.getByRole("heading", { name: "Something went wrong on this page" })).toBeInTheDocument();
		expect(screen.getByText("cannot read properties of undefined")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
	});
});
