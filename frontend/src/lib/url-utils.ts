/**
 * URL validation and handling utilities
 *
 * This module uses the native URL constructor for validation instead of regex
 * for the following reasons:
 *
 * 1. Security: Browser-native parsing prevents bypass vulnerabilities (XSS, protocol confusion)
 * 2. Standards compliance: Uses WHATWG URL specification
 * 3. Edge case handling: Correctly handles IPv6, internationalized domains, etc.
 * 4. Maintainability: No complex regex to maintain or update
 *
 * See frontend/docs/url-validation-tradeoffs.md for detailed comparison.
 */

/**
 * Checks if a string is a valid URL with http/https protocol
 *
 * This function validates URLs for use in hyperlinks. It only accepts http/https
 * protocols to prevent security issues like XSS via javascript:, data:, or file: URIs.
 *
 * @param str - String to validate
 * @returns true if the string is a valid URL with http/https protocol, false otherwise
 *
 * @example
 * isValidUrl("https://example.com") // true
 * isValidUrl("intacct service request faq") // false
 * isValidUrl("javascript:alert('xss')") // false (security protection)
 */
export function isValidUrl(str: string): boolean {
  if (!str || typeof str !== "string") {
    return false;
  }

  try {
    const url = new URL(str);
    // Only accept http and https protocols
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    // URL constructor throws if the string is not a valid URL
    return false;
  }
}
