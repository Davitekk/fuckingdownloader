import assert from "node:assert/strict";
import test from "node:test";
import { netscapeCookies } from "./cookies.mjs";

const sample = {
  domain: ".tiktok.com",
  hostOnly: false,
  path: "/",
  secure: true,
  httpOnly: true,
  name: "example",
  value: "dummy-session",
};

test("preserves Netscape flags, including HttpOnly and session expiry", () => {
  assert.equal(netscapeCookies([sample]),
    "# Netscape HTTP Cookie File\n#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t0\texample\tdummy-session\n");
});

test("excludes unrelated, partitioned, and malformed rows", () => {
  assert.equal(netscapeCookies([
    { ...sample, domain: "tiktok.com.example.org" },
    { ...sample, domain: "nottiktok.com" },
    { ...sample, partitionKey: { topLevelSite: "https://example.org" } },
    { ...sample, value: "invalid\tfield" },
  ]), null);
});
