import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// findBy* / waitFor wait 1s by default; under a full parallel run a page's first fetches
// and render can take longer, which failed tests that pass alone.
configure({ asyncUtilTimeout: 3000 });

afterEach(() => {
  cleanup();
});
