/* eslint-disable */
/**
 * Settings Panel E2E Test
 * Exercises every control on the Settings page and reports bugs.
 */

const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const SCREENSHOTS_DIR = path.join(__dirname, "screenshots");
if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

const bugs = [];
const consoleErrors = [];
const networkErrors = [];

function logBug(title, steps, expected, actual, screenshotPath, severity) {
  bugs.push({ title, steps, expected, actual, screenshotPath, severity });
}

async function run() {
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
  });

  // Capture console logs
  context.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") {
      consoleErrors.push({ type: msg.type(), text: msg.text() });
    }
  });

  const page = await context.newPage();

  // Track network failures
  page.on("requestfailed", (req) => {
    // Only flag non-expected API failures (UI-layer issues)
    const url = req.url();
    networkErrors.push({ url, failure: req.failure()?.errorText });
  });

  // Track API responses (non-2xx)
  page.on("response", async (res) => {
    if (!res.ok() && res.status() !== 0) {
      const url = res.url();
      networkErrors.push({ url, status: res.status() });
    }
  });

  // ─────────────────────────────────────────────────────────────
  // 1. Navigate and open Settings
  // ─────────────────────────────────────────────────────────────
  await page.goto("http://localhost:3000", { waitUntil: "networkidle", timeout: 15000 });
  await page.screenshot({ path: `${SCREENSHOTS_DIR}/01_initial_load.png` });

  // Click Settings nav button
  const settingsBtn = page.locator("button:has-text('Settings')");
  await settingsBtn.waitFor({ timeout: 5000 });
  await settingsBtn.click();

  // Wait for the page to settle (API calls happen on mount)
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${SCREENSHOTS_DIR}/02_settings_loaded.png` });

  // ─────────────────────────────────────────────────────────────
  // 2. Check loading state vs content/error state
  // ─────────────────────────────────────────────────────────────
  const errorText = await page.locator("text=Failed to load settings").count();
  const settingsHeader = await page.locator("h2:has-text('Settings')").count();

  if (errorText > 0) {
    // Backend is offline – we expect this, but check for graceful error display
    const hasErrorMessage = await page.locator(".text-red-400, .text-red-300").count();
    if (!hasErrorMessage) {
      logBug(
        "No visual error feedback when API is unavailable",
        [
          "1. Open http://localhost:3000",
          "2. Click Settings",
          "3. Wait for load (backend is offline)",
        ],
        "A visible error message should appear",
        "No error message is rendered",
        `${SCREENSHOTS_DIR}/02_settings_loaded.png`,
        "High"
      );
    }
    console.log("Backend offline - settings shows error state. Proceeding with mock-mode analysis.");

    // Check: does the loading shimmer persist indefinitely when API fails?
    const shimmerVisible = await page.locator(".animate-pulse").count();
    if (shimmerVisible > 0) {
      logBug(
        "Loading shimmer persists indefinitely on API failure",
        [
          "1. Open http://localhost:3000",
          "2. Click Settings tab",
          "3. Wait 5+ seconds with backend offline",
        ],
        "Error state or retry button should replace the shimmer",
        "Shimmer/loading animation continues indefinitely",
        `${SCREENSHOTS_DIR}/02_settings_loaded.png`,
        "High"
      );
    }

    await browser.close();
    return { bugs, consoleErrors, networkErrors, screenshots: SCREENSHOTS_DIR };
  }

  if (!settingsHeader) {
    logBug(
      "Settings panel header not rendered",
      ["1. Click Settings nav button"],
      "h2 with 'Settings' text should appear",
      "No settings header found",
      `${SCREENSHOTS_DIR}/02_settings_loaded.png`,
      "Critical"
    );
  }

  // ─────────────────────────────────────────────────────────────
  // 3. Health status indicator
  // ─────────────────────────────────────────────────────────────
  const healthDot = page.locator(".w-3.h-3.rounded-full");
  const healthDotCount = await healthDot.count();
  if (healthDotCount === 0) {
    logBug(
      "Health status indicator missing",
      ["1. Open Settings tab"],
      "A colored dot and 'Service Status' label should be visible",
      "No health indicator dot found",
      `${SCREENSHOTS_DIR}/02_settings_loaded.png`,
      "Low"
    );
  }

  // ─────────────────────────────────────────────────────────────
  // 4. Test sliders
  // ─────────────────────────────────────────────────────────────
  const sliders = page.locator("input[type='range']");
  const sliderCount = await sliders.count();
  console.log(`Found ${sliderCount} sliders`);

  if (sliderCount < 4) {
    logBug(
      `Expected at least 4 sliders, found ${sliderCount}`,
      ["1. Open Settings tab", "2. Count input[type=range] elements"],
      "4 sliders: Semantic Top-K, Keyword Top-K, Final Top-K, Semantic Weight, Keyword Weight (+ Pre-Rerank if enabled)",
      `Only ${sliderCount} sliders present`,
      `${SCREENSHOTS_DIR}/02_settings_loaded.png`,
      "High"
    );
  }

  // ─────────────────────────────────────────────────────────────
  // 5. Semantic Weight slider — test auto-adjust logic
  // ─────────────────────────────────────────────────────────────
  // Get initial values from labels
  const semanticWeightLabelBefore = await page.locator("label:has-text('Semantic Weight:')").textContent();
  const keywordWeightLabelBefore = await page.locator("label:has-text('Keyword Weight:')").textContent();
  console.log("Before:", semanticWeightLabelBefore, keywordWeightLabelBefore);

  // Find the semantic weight slider (4th slider if rerank is off, index 3)
  // Sliders: semantic_top_k(0), keyword_top_k(1), final_top_k(2), semantic_weight(3), keyword_weight(4)
  const semanticWeightSlider = sliders.nth(3);
  const initialSemanticVal = await semanticWeightSlider.inputValue();

  // Fill to a specific value (range sliders use fill with numeric string matching step)
  await semanticWeightSlider.evaluate((el) => {
    el.value = "0.7";
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.waitForTimeout(300);

  const semanticWeightLabelAfter = await page.locator("label:has-text('Semantic Weight:')").textContent();
  const keywordWeightLabelAfter = await page.locator("label:has-text('Keyword Weight:')").textContent();
  console.log("After changing semantic to 0.70:", semanticWeightLabelAfter, keywordWeightLabelAfter);

  // The label should now show 0.70
  if (!semanticWeightLabelAfter?.includes("0.70")) {
    logBug(
      "Semantic Weight slider label not updating on change",
      [
        "1. Open Settings tab",
        "2. Move Semantic Weight slider to 0.70",
      ],
      "Label should show 'Semantic Weight: 0.70'",
      `Label shows: ${semanticWeightLabelAfter}`,
      `${SCREENSHOTS_DIR}/02_settings_loaded.png`,
      "High"
    );
  }

  // ─────────────────────────────────────────────────────────────
  // 6. Test weight auto-adjust bug:
  //    The auto-adjust code in handleConfigChange ONLY fires when
  //    semantic_weight + keyword_weight !== 1.  But when they DO
  //    sum to 1 the code falls through to the plain setConfig,
  //    so changing semantic weight does NOT adjust keyword weight.
  // ─────────────────────────────────────────────────────────────
  await page.screenshot({ path: `${SCREENSHOTS_DIR}/03_after_slider_change.png` });

  // Read keyword weight label now
  const keywordValAfterSemanticChange = await page.locator("label:has-text('Keyword Weight:')").textContent();
  const semanticValAfterChange = await page.locator("label:has-text('Semantic Weight:')").textContent();

  // Extract numeric values
  const extractFloat = (text) => {
    const match = text?.match(/[\d.]+$/);
    return match ? parseFloat(match[0]) : null;
  };

  const semVal = extractFloat(semanticValAfterChange);
  const kwVal = extractFloat(keywordValAfterSemanticChange);

  console.log(`Semantic: ${semVal}, Keyword: ${kwVal}, Sum: ${semVal + kwVal}`);

  if (semVal !== null && kwVal !== null) {
    const sum = parseFloat((semVal + kwVal).toFixed(2));
    if (Math.abs(sum - 1.0) > 0.01) {
      logBug(
        "Semantic + Keyword weights do not sum to 1.0 after slider adjustment",
        [
          "1. Open Settings tab (backend must be online with default weights summing to 1.0)",
          "2. Move Semantic Weight slider to 0.70",
          "3. Observe Keyword Weight label",
        ],
        "Keyword Weight should auto-adjust to 0.30 so both sum to 1.0",
        `Semantic=${semVal}, Keyword=${kwVal}, Sum=${sum} (not 1.0)`,
        `${SCREENSHOTS_DIR}/03_after_slider_change.png`,
        "High"
      );
    }
  }

  // ─────────────────────────────────────────────────────────────
  // 7. Weight auto-adjust condition bug analysis
  //    The condition checks: semantic_weight + keyword_weight !== 1
  //    When they DO sum to 1 (default state), moving one slider
  //    will NOT auto-adjust the other — the condition is inverted.
  // ─────────────────────────────────────────────────────────────
  // Reset to known state by setting semantic = 0.65 (typical default)
  await semanticWeightSlider.evaluate((el) => {
    el.value = "0.65";
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.waitForTimeout(300);

  const semAfterReset = extractFloat(await page.locator("label:has-text('Semantic Weight:')").textContent());
  const kwAfterReset = extractFloat(await page.locator("label:has-text('Keyword Weight:')").textContent());
  console.log(`After reset: sem=${semAfterReset}, kw=${kwAfterReset}, sum=${semAfterReset + kwAfterReset}`);

  if (semAfterReset !== null && kwAfterReset !== null) {
    const resetSum = parseFloat((semAfterReset + kwAfterReset).toFixed(2));
    // If weights now sum to 1.0, test the broken auto-adjust
    if (Math.abs(resetSum - 1.0) <= 0.01) {
      // Now move semantic slider — with the inverted condition the adjust will NOT fire
      await semanticWeightSlider.evaluate((el) => {
        el.value = "0.8";
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await page.waitForTimeout(300);

      const semNew = extractFloat(await page.locator("label:has-text('Semantic Weight:')").textContent());
      const kwNew = extractFloat(await page.locator("label:has-text('Keyword Weight:')").textContent());
      console.log(`After moving to 0.80: sem=${semNew}, kw=${kwNew}, sum=${semNew+kwNew}`);

      const newSum = parseFloat((semNew + kwNew).toFixed(2));
      if (Math.abs(newSum - 1.0) > 0.01) {
        logBug(
          "Weight auto-adjust does not fire when weights initially sum to 1.0 (inverted condition bug)",
          [
            "1. Open Settings tab with default config (semantic_weight=0.65, keyword_weight=0.35, sum=1.0)",
            "2. Move Semantic Weight slider from 0.65 to 0.80",
            "3. Observe Keyword Weight label",
          ],
          "Keyword Weight should auto-adjust to 0.20 so weights always sum to 1.0",
          `Keyword Weight remains ${kwNew} (sum = ${newSum}, not 1.0). The auto-adjust condition '!== 1' is inverted — it only triggers when weights DON'T sum to 1, which is backwards.`,
          `${SCREENSHOTS_DIR}/03_after_slider_change.png`,
          "Critical"
        );
      }
      await page.screenshot({ path: `${SCREENSHOTS_DIR}/04_weight_autoadjust_test.png` });
    }
  }

  // ─────────────────────────────────────────────────────────────
  // 8. Enable Reranking toggle
  // ─────────────────────────────────────────────────────────────
  const rerankCheckbox = page.locator("input[type='checkbox']");
  const rerankChecked = await rerankCheckbox.isChecked();
  console.log(`Rerank enabled: ${rerankChecked}`);

  const preRerankSliderBefore = await page.locator("input[type='range']").count();

  // Toggle rerank on
  if (!rerankChecked) {
    await rerankCheckbox.click();
    await page.waitForTimeout(300);
  }

  const preRerankSliderAfter = await page.locator("input[type='range']").count();

  if (preRerankSliderAfter <= preRerankSliderBefore && !rerankChecked) {
    logBug(
      "Pre-Rerank Top-K slider not shown when reranking enabled",
      [
        "1. Open Settings tab",
        "2. Check 'Enable cross-encoder reranking'",
      ],
      "A Pre-Rerank Top-K slider should appear",
      "Slider count unchanged after enabling reranking",
      `${SCREENSHOTS_DIR}/02_settings_loaded.png`,
      "High"
    );
  }

  await page.screenshot({ path: `${SCREENSHOTS_DIR}/05_rerank_enabled.png` });

  // Toggle rerank off
  await rerankCheckbox.click();
  await page.waitForTimeout(300);
  const preRerankSliderOff = await page.locator("input[type='range']").count();
  if (preRerankSliderOff >= preRerankSliderAfter) {
    logBug(
      "Pre-Rerank Top-K slider not hidden when reranking disabled",
      [
        "1. Enable reranking checkbox",
        "2. Disable reranking checkbox",
      ],
      "Pre-Rerank Top-K slider should disappear",
      "Slider still visible after disabling reranking",
      `${SCREENSHOTS_DIR}/05_rerank_enabled.png`,
      "Medium"
    );
  }

  // ─────────────────────────────────────────────────────────────
  // 9. New Collection Name field — validation
  // ─────────────────────────────────────────────────────────────
  const collectionInput = page.locator("#new-collection-name");
  const createBtn = page.locator("button[aria-label='Create and switch to new collection']");

  // Test: empty input — button should be disabled
  await collectionInput.fill("");
  await page.waitForTimeout(100);
  const disabledOnEmpty = await createBtn.isDisabled();
  if (!disabledOnEmpty) {
    logBug(
      "Create & Switch button enabled with empty collection name",
      [
        "1. Open Settings tab",
        "2. Leave New Collection Name field empty",
        "3. Check 'Create & Switch' button state",
      ],
      "Button should be disabled when field is empty",
      "Button is enabled with empty input",
      `${SCREENSHOTS_DIR}/02_settings_loaded.png`,
      "High"
    );
  }

  // Test: too-short name (5 chars — min is 6)
  await collectionInput.fill("abc12");
  await page.waitForTimeout(200);
  const validationMsg5 = await page.locator("text=Must be 6").count();
  const disabledOn5 = await createBtn.isDisabled();
  await page.screenshot({ path: `${SCREENSHOTS_DIR}/06_collection_validation_short.png` });

  if (!validationMsg5) {
    logBug(
      "No validation message for collection name shorter than 6 characters",
      [
        "1. Open Settings tab",
        "2. Type 'abc12' (5 chars) in New Collection Name",
      ],
      "Validation error should appear: 'Must be 6–20 characters...'",
      "No validation message shown",
      `${SCREENSHOTS_DIR}/06_collection_validation_short.png`,
      "Medium"
    );
  }
  if (!disabledOn5) {
    logBug(
      "Create & Switch button enabled with 5-character collection name (below minimum of 6)",
      [
        "1. Open Settings tab",
        "2. Type 'abc12' (5 chars) in New Collection Name",
        "3. Check button state",
      ],
      "Button should remain disabled",
      "Button is enabled",
      `${SCREENSHOTS_DIR}/06_collection_validation_short.png`,
      "High"
    );
  }

  // Test: valid 6-char name
  await collectionInput.fill("abc123");
  await page.waitForTimeout(200);
  const disabledOnValid = await createBtn.isDisabled();
  await page.screenshot({ path: `${SCREENSHOTS_DIR}/07_collection_valid.png` });

  if (disabledOnValid) {
    logBug(
      "Create & Switch button disabled with valid 6-character collection name",
      [
        "1. Open Settings tab",
        "2. Type 'abc123' (6 chars, all valid characters) in New Collection Name",
        "3. Check button state",
      ],
      "Button should be enabled for valid name",
      "Button is disabled",
      `${SCREENSHOTS_DIR}/07_collection_valid.png`,
      "Medium"
    );
  }

  // Test: 21-char name (too long — max is 20)
  await collectionInput.fill("abcdefghijklmnopqrstu");
  await page.waitForTimeout(200);
  const disabledOn21 = await createBtn.isDisabled();
  const validationMsg21 = await page.locator("text=Must be 6").count();
  await page.screenshot({ path: `${SCREENSHOTS_DIR}/08_collection_too_long.png` });

  if (!disabledOn21) {
    logBug(
      "Create & Switch button enabled with 21-character collection name (above maximum of 20)",
      [
        "1. Open Settings tab",
        "2. Type 21 alphanumeric characters in New Collection Name",
        "3. Check button state",
      ],
      "Button should be disabled (max is 20 chars)",
      "Button is enabled",
      `${SCREENSHOTS_DIR}/08_collection_too_long.png`,
      "Medium"
    );
  }
  if (!validationMsg21) {
    logBug(
      "No validation message for collection name longer than 20 characters",
      [
        "1. Type 21 alphanumeric chars in New Collection Name",
      ],
      "Validation message should appear",
      "No validation message shown",
      `${SCREENSHOTS_DIR}/08_collection_too_long.png`,
      "Low"
    );
  }

  // Test: special characters
  await collectionInput.fill("my collection!");
  await page.waitForTimeout(200);
  const disabledOnSpecial = await createBtn.isDisabled();
  await page.screenshot({ path: `${SCREENSHOTS_DIR}/09_collection_special_chars.png` });

  if (!disabledOnSpecial) {
    logBug(
      "Create & Switch button enabled with special characters in collection name",
      [
        "1. Open Settings tab",
        "2. Type 'my collection!' in New Collection Name",
        "3. Check button state",
      ],
      "Button should be disabled (spaces and ! are invalid)",
      "Button is enabled",
      `${SCREENSHOTS_DIR}/09_collection_special_chars.png`,
      "High"
    );
  }

  // ─────────────────────────────────────────────────────────────
  // 10. Active Collection dropdown
  // ─────────────────────────────────────────────────────────────
  const collectionSelect = page.locator("#active-collection");
  const selectCount = await collectionSelect.count();
  if (selectCount === 0) {
    logBug(
      "Active Collection dropdown not found",
      ["1. Open Settings tab"],
      "A dropdown with id 'active-collection' should be visible",
      "Dropdown not found",
      `${SCREENSHOTS_DIR}/02_settings_loaded.png`,
      "High"
    );
  } else {
    const options = await collectionSelect.locator("option").count();
    console.log(`Collection dropdown options: ${options}`);

    // Check: current collection_name should appear as an option even if it's
    // not in the collections list. The code adds a synthetic {name, count: 0}
    // entry. Check if 0 docs is shown for the current collection.
    const allOptionsText = await collectionSelect.allInnerTexts();
    console.log("Options text:", allOptionsText);
  }

  // ─────────────────────────────────────────────────────────────
  // 11. Save Settings button — check feedback
  // ─────────────────────────────────────────────────────────────
  const saveBtn = page.locator("button:has-text('Save Settings')");
  const saveBtnCount = await saveBtn.count();
  if (saveBtnCount === 0) {
    logBug(
      "Save Settings button not found",
      ["1. Open Settings tab"],
      "A 'Save Settings' button should be at the bottom",
      "Button not found",
      `${SCREENSHOTS_DIR}/02_settings_loaded.png`,
      "Critical"
    );
  }

  // Click Save and check feedback
  await collectionInput.fill(""); // Clear the invalid input first
  await saveBtn.click();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${SCREENSHOTS_DIR}/10_after_save.png` });

  // Check for message (success or error) after save attempt
  const successMsg = await page.locator("text=Settings saved").count();
  const errorMsg = await page.locator(".bg-red-500\\/20, .bg-green-500\\/20").count();

  if (!successMsg && !errorMsg) {
    logBug(
      "No feedback message displayed after clicking Save Settings",
      [
        "1. Open Settings tab",
        "2. Click 'Save Settings' button",
        "3. Wait 2 seconds",
      ],
      "A success or error message should appear below the form",
      "No feedback message shown",
      `${SCREENSHOTS_DIR}/10_after_save.png`,
      "High"
    );
  }

  // ─────────────────────────────────────────────────────────────
  // 12. Check: message persists vs clears on re-interaction
  // ─────────────────────────────────────────────────────────────
  const msgVisibleBefore = await page.locator(".bg-red-500\\/20, .bg-green-500\\/20").count();
  if (msgVisibleBefore > 0) {
    // Move a slider — message should clear or persist (document behavior)
    const firstSlider = sliders.first();
    const currentVal = await firstSlider.inputValue();
    const newVal = currentVal === "1" ? "2" : String(parseInt(currentVal) - 1);
    await firstSlider.fill(newVal);
    await page.waitForTimeout(200);

    const msgAfterInteraction = await page.locator(".bg-red-500\\/20, .bg-green-500\\/20").count();
    // Note: this is not necessarily a bug, just documenting behavior
    console.log(`Message after slider interaction: ${msgAfterInteraction > 0 ? "still visible" : "cleared"}`);
  }

  // ─────────────────────────────────────────────────────────────
  // 13. Keyboard accessibility — Tab navigation
  // ─────────────────────────────────────────────────────────────
  await page.keyboard.press("Tab");
  await page.waitForTimeout(100);
  const focusedEl = await page.evaluate(() => document.activeElement?.tagName);
  console.log(`After Tab key: focused element = ${focusedEl}`);

  // ─────────────────────────────────────────────────────────────
  // 14. Check: isSaving state during Create — both buttons disabled
  // ─────────────────────────────────────────────────────────────
  // Rapid-click test: click Save multiple times quickly
  if (saveBtnCount > 0) {
    await saveBtn.click();
    await saveBtn.click();
    await saveBtn.click();
    await page.waitForTimeout(100);

    const saveBtnText = await saveBtn.textContent();
    // After first click it should say "Saving..." and be disabled
    // If rapid clicks cause it to re-enter saving state, that's a bug
    console.log(`Save button text after rapid clicks: "${saveBtnText}"`);
  }

  // ─────────────────────────────────────────────────────────────
  // 15. Final screenshot
  // ─────────────────────────────────────────────────────────────
  await page.screenshot({ path: `${SCREENSHOTS_DIR}/11_final_state.png`, fullPage: true });

  // ─────────────────────────────────────────────────────────────
  // 16. Check for console errors (filter known/expected backend errors)
  // ─────────────────────────────────────────────────────────────
  const unexpectedConsoleErrors = consoleErrors.filter((e) => {
    const text = e.text.toLowerCase();
    // Skip expected network errors from backend being offline
    if (text.includes("failed to fetch") || text.includes("net::err_connection_refused")) return false;
    return true;
  });

  if (unexpectedConsoleErrors.length > 0) {
    logBug(
      `Unexpected browser console errors (${unexpectedConsoleErrors.length})`,
      ["1. Open Settings tab", "2. Interact with controls"],
      "No console errors",
      unexpectedConsoleErrors.slice(0, 3).map((e) => `[${e.type}] ${e.text}`).join("\n"),
      `${SCREENSHOTS_DIR}/11_final_state.png`,
      "Medium"
    );
  }

  await browser.close();
  return { bugs, consoleErrors, networkErrors, screenshots: SCREENSHOTS_DIR };
}

run()
  .then((result) => {
    console.log("\n========== TEST RESULTS ==========");
    console.log(JSON.stringify(result, null, 2));
  })
  .catch((err) => {
    console.error("Test runner error:", err);
    process.exit(1);
  });
