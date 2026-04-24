/**
 * URL validation and handling utilities
 */

/**
 * Checks if a string is a valid URL with http/https protocol
 * @param str - String to validate
 * @returns true if the string is a valid URL with http/https protocol, false otherwise
 */
export function isValidUrl(str: string): boolean {
  if (!str || typeof str !== 'string') {
    return false;
  }

  try {
    const url = new URL(str);
    // Only accept http and https protocols
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}
