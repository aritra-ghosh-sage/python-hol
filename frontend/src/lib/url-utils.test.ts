import { describe, expect, it } from "vitest";
import { isValidUrl } from "./url-utils";

describe("isValidUrl", () => {
  it("should return true for valid http URLs", () => {
    expect(isValidUrl("http://example.com")).toBe(true);
    expect(isValidUrl("http://www.example.com")).toBe(true);
    expect(isValidUrl("http://example.com/path")).toBe(true);
    expect(isValidUrl("http://example.com/path?query=value")).toBe(true);
    expect(isValidUrl("http://example.com:8080")).toBe(true);
  });

  it("should return true for valid https URLs", () => {
    expect(isValidUrl("https://example.com")).toBe(true);
    expect(isValidUrl("https://www.example.com")).toBe(true);
    expect(isValidUrl("https://support.google.com/maps/answer/144349")).toBe(true);
    expect(isValidUrl("https://github.com/user/repo")).toBe(true);
    expect(isValidUrl("https://api.example.com/v1/users")).toBe(true);
  });

  it("should return false for plain text without protocol", () => {
    expect(isValidUrl("example.com")).toBe(false);
    expect(isValidUrl("www.example.com")).toBe(false);
    expect(isValidUrl("intacct service request faq")).toBe(false);
    expect(isValidUrl("document title")).toBe(false);
    expect(isValidUrl("my-file.pdf")).toBe(false);
  });

  it("should return false for invalid protocols", () => {
    expect(isValidUrl("ftp://example.com")).toBe(false);
    expect(isValidUrl("file:///path/to/file")).toBe(false);
    expect(isValidUrl("javascript:alert('xss')")).toBe(false);
    expect(isValidUrl("data:text/html,<h1>Test</h1>")).toBe(false);
  });

  it("should return false for empty or invalid input", () => {
    expect(isValidUrl("")).toBe(false);
    expect(isValidUrl(" ")).toBe(false);
    // @ts-expect-error Testing invalid input
    expect(isValidUrl(null)).toBe(false);
    // @ts-expect-error Testing invalid input
    expect(isValidUrl(undefined)).toBe(false);
    // @ts-expect-error Testing invalid input
    expect(isValidUrl(123)).toBe(false);
  });

  it("should return false for malformed URLs", () => {
    expect(isValidUrl("http://")).toBe(false);
    expect(isValidUrl("https://")).toBe(false);
    expect(isValidUrl("://example.com")).toBe(false);
    expect(isValidUrl("htp://example.com")).toBe(false);
  });

  it("should handle edge cases", () => {
    expect(isValidUrl("https://localhost")).toBe(true);
    expect(isValidUrl("http://127.0.0.1")).toBe(true);
    expect(isValidUrl("https://192.168.1.1:3000")).toBe(true);
    expect(isValidUrl("https://example.com/#anchor")).toBe(true);
  });

  describe("security validations", () => {
    it("should prevent XSS via javascript: protocol", () => {
      expect(isValidUrl("javascript:alert('xss')")).toBe(false);
      expect(isValidUrl("javascript:void(0)")).toBe(false);
      expect(isValidUrl("JAVASCRIPT:alert(document.cookie)")).toBe(false);
    });

    it("should prevent data: URI injection", () => {
      expect(isValidUrl("data:text/html,<script>alert('xss')</script>")).toBe(false);
      expect(isValidUrl("data:text/html;base64,PHNjcmlwdD5hbGVydCgneHNzJyk8L3NjcmlwdD4=")).toBe(false);
    });

    it("should prevent file: protocol access", () => {
      expect(isValidUrl("file:///etc/passwd")).toBe(false);
      expect(isValidUrl("file:///C:/Windows/System32/config/sam")).toBe(false);
    });

    it("should prevent protocol-relative URLs", () => {
      // Protocol-relative URLs can be used for bypasses
      expect(isValidUrl("//evil.com/payload")).toBe(false);
      expect(isValidUrl("///evil.com")).toBe(false);
    });

    it("should handle URL constructor normalization", () => {
      // URL constructor is smart and normalizes many edge cases
      // This demonstrates why URL constructor is better than regex:
      // it handles edge cases correctly according to the spec
      expect(isValidUrl("http:///example.com")).toBe(true); // normalized to http://example.com/
      expect(isValidUrl("https:example.com")).toBe(true); // normalized to https://example.com/

      // These are truly invalid
      expect(isValidUrl("ht tp://example.com")).toBe(false); // space in protocol
      expect(isValidUrl("http//example.com")).toBe(false); // missing colon
    });
  });
});
