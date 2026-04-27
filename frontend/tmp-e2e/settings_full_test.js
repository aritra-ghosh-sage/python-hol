/* eslint-disable */
const { chromium } = require("/home/aritraghosh/projects/python-hol/frontend/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const SCREENSHOTS = "/home/aritraghosh/projects/python-hol/frontend/tmp-e2e/screenshots";
if (!fs.existsSync(SCREENSHOTS)) fs.mkdirSync(SCREENSHOTS, { recursive: true });

const bugs = [];
const consoleLogs = [];

function logBug(title, steps, expected, actual, screenshot, severity) {
  console.log("[BUG][" + severity + "] " + title);
  bugs.push({ title, steps, expected, actual, screenshot, severity });
}

async function run() {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on("console", (msg) => consoleLogs.push({ type: msg.type(), text: msg.text() }));

  await page.goto("http://localhost:3000", { waitUntil: "networkidle", timeout: 15000 });
  await page.locator("button:has-text('Settings')").click();
  await page.waitForTimeout(3000);
  await page.screenshot({ path: SCREENSHOTS + "/01_settings_initial.png" });

  // TEST 1: Slider accessibility (no aria-label / id)
  const sliderData = await page.evaluate(() => {
    const sliders = Array.from(document.querySelectorAll("input[type=range]"));
    return sliders.map((s, i) => ({
      index: i,
      ariaLabel: s.getAttribute("aria-label"),
      id: s.id,
      value: s.value,
    }));
  });
  const badSliders = sliderData.filter((s) => !s.ariaLabel && !s.id);
  console.log("Sliders without aria-label or id: " + badSliders.length + " of " + sliderData.length);
  if (badSliders.length > 0) {
    logBug(
      "Range sliders missing aria-label and id attributes",
      ["1. Open Settings tab", "2. Inspect any range slider in DevTools"],
      "Each slider should have an aria-label or id for accessibility",
      badSliders.length + " slider(s) have neither (indices: " + badSliders.map((s) => s.index).join(", ") + ")",
      SCREENSHOTS + "/01_settings_initial.png",
      "Medium"
    );
  }

  // TEST 2: Initial weights
  const semLabel0 = await page.locator("label:has-text('Semantic Weight:')").textContent();
  const kwLabel0 = await page.locator("label:has-text('Keyword Weight:')").textContent();
  const sem0 = parseFloat((semLabel0 || "").match(/[\d.]+$/)?.[0] || "0");
  const kw0 = parseFloat((kwLabel0 || "").match(/[\d.]+$/)?.[0] || "0");
  const sum0 = parseFloat((sem0 + kw0).toFixed(4));
  console.log("Initial weights: sem=" + sem0 + " kw=" + kw0 + " sum=" + sum0);

  // TEST 3: Auto-adjust bug
  const semSlider = page.locator("input[type=range]").nth(3);
  const kwSlider = page.locator("input[type=range]").nth(4);

  await semSlider.focus();
  await page.keyboard.press("ArrowLeft");
  await page.waitForTimeout(300);

  const sem1 = parseFloat(await semSlider.inputValue());
  const kw1 = parseFloat(await kwSlider.inputValue());
  const sum1 = parseFloat((sem1 + kw1).toFixed(4));
  console.log("After sem ArrowLeft: sem=" + sem1 + " kw=" + kw1 + " sum=" + sum1);
  await page.screenshot({ path: SCREENSHOTS + "/02_weight_autoadjust.png" });

  if (Math.abs(sum0 - 1.0) <= 0.001 && Math.abs(sum1 - 1.0) > 0.001) {
    logBug(
      "Weight auto-adjust does not fire when weights initially sum to 1.0 (inverted condition bug)",
      [
        "1. Open Settings tab — default weights: semantic=0.70, keyword=0.30, sum=1.0",
        "2. Click Semantic Weight slider",
        "3. Press ArrowLeft (decrease by one step = 0.05)",
        "4. Observe Keyword Weight value",
      ],
      "Keyword Weight should increase by 0.05 so both still sum to 1.0 (e.g., sem=0.65 kw=0.35)",
      "Semantic Weight changed from " + sem0 + " to " + sem1 +
        " but Keyword Weight stayed at " + kw1 +
        ". Sum is now " + sum1 + " instead of 1.0. " +
        "Root cause in handleConfigChange (SettingsPanel.tsx line 51): " +
        "condition `semantic_weight + keyword_weight !== 1` is inverted — " +
        "it only auto-adjusts when weights are ALREADY out of balance, " +
        "not when they are in balance and a slider moves.",
      SCREENSHOTS + "/02_weight_autoadjust.png",
      "Critical"
    );
  }

  // TEST 3b: Confirm backwards auto-adjust fires on second move
  await semSlider.focus();
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(300);
  const sem2 = parseFloat(await semSlider.inputValue());
  const kw2 = parseFloat(await kwSlider.inputValue());
  const sum2 = parseFloat((sem2 + kw2).toFixed(4));
  console.log("After second move (sem ArrowRight): sem=" + sem2 + " kw=" + kw2 + " sum=" + sum2);

  if (
    Math.abs(sum1 - 1.0) > 0.001 &&
    Math.abs(sum2 - 1.0) <= 0.001
  ) {
    // Sum returned to 1.0 because now the broken state (sum != 1) triggered auto-adjust
    logBug(
      "Weight auto-adjust fires on second slider move (when sum != 1.0) but not on first (when sum = 1.0)",
      [
        "1. Open Settings (weights sum to 1.0)",
        "2. Move Semantic Weight slider ArrowLeft — weights now != 1.0 (auto-adjust does NOT fire)",
        "3. Move Semantic Weight slider ArrowRight — auto-adjust fires because sum != 1.0",
        "4. Observe weights return to 1.0 only after the second move",
      ],
      "Auto-adjust should fire on every slider change to maintain sum of 1.0",
      "Auto-adjust fires on step 3 (sum != 1.0 condition is true) but not step 2 (sum = 1.0). " +
        "This causes a one-step lag where the UI shows invalid weights.",
      SCREENSHOTS + "/02_weight_autoadjust.png",
      "High"
    );
  }
  await page.screenshot({ path: SCREENSHOTS + "/03_weight_second_move.png" });

  // TEST 4: Multiple rapid slider moves — accumulating drift
  for (let i = 0; i < 6; i++) {
    await semSlider.focus();
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(50);
  }
  await page.waitForTimeout(300);
  const semFinal = parseFloat(await semSlider.inputValue());
  const kwFinal = parseFloat(await kwSlider.inputValue());
  const sumFinal = parseFloat((semFinal + kwFinal).toFixed(4));
  console.log("After 6x ArrowRight: sem=" + semFinal + " kw=" + kwFinal + " sum=" + sumFinal);
  await page.screenshot({ path: SCREENSHOTS + "/04_rapid_slider.png" });

  if (Math.abs(sumFinal - 1.0) > 0.01) {
    logBug(
      "Weights drift far from 1.0 after multiple rapid slider changes",
      [
        "1. Open Settings tab",
        "2. Click Semantic Weight slider and press ArrowRight 6 times rapidly",
      ],
      "Weights should always sum to 1.0",
      "After 6 ArrowRight presses: sem=" + semFinal + " kw=" + kwFinal + " sum=" + sumFinal,
      SCREENSHOTS + "/04_rapid_slider.png",
      "High"
    );
  }

  // TEST 5: Rerank toggle shows/hides Pre-Rerank slider
  const rerankCheckbox = page.locator("input[type=checkbox]");
  if (!(await rerankCheckbox.isChecked())) await rerankCheckbox.click();
  await page.waitForTimeout(300);
  const sliderCountOn = await page.locator("input[type=range]").count();
  await page.screenshot({ path: SCREENSHOTS + "/05_rerank_on.png" });

  await rerankCheckbox.click();
  await page.waitForTimeout(300);
  const sliderCountOff = await page.locator("input[type=range]").count();
  await page.screenshot({ path: SCREENSHOTS + "/06_rerank_off.png" });

  console.log("Slider count — rerank ON: " + sliderCountOn + ", OFF: " + sliderCountOff);
  if (sliderCountOn !== sliderCountOff + 1) {
    logBug(
      "Pre-Rerank Top-K slider does not toggle correctly with reranking checkbox",
      ["1. Enable reranking checkbox", "2. Disable reranking checkbox"],
      "One extra slider should appear when enabled (count ON = count OFF + 1)",
      "ON=" + sliderCountOn + " OFF=" + sliderCountOff,
      SCREENSHOTS + "/05_rerank_on.png",
      "High"
    );
  }

  // TEST 6: Collection name validation edge cases
  const collectionInput = page.locator("#new-collection-name");
  const createBtn = page.locator("button[aria-label='Create and switch to new collection']");

  const testCases = [
    { value: "",              expectDisabled: true,  tag: "empty" },
    { value: "ab_12",         expectDisabled: true,  tag: "5_chars_below_min" },
    { value: "ab_123",        expectDisabled: false, tag: "6_chars_exact_min" },
    { value: "a".repeat(20),  expectDisabled: false, tag: "20_chars_exact_max" },
    { value: "a".repeat(21),  expectDisabled: true,  tag: "21_chars_above_max" },
    { value: "my collection!", expectDisabled: true,  tag: "spaces_special_chars" },
    { value: "valid-name_01", expectDisabled: false, tag: "hyphen_underscore_valid" },
  ];

  for (const tc of testCases) {
    // Use triple-click + type to ensure full replacement
    await collectionInput.click({ clickCount: 3 });
    if (tc.value) {
      await page.keyboard.type(tc.value);
    } else {
      await page.keyboard.press("Delete");
    }
    await page.waitForTimeout(250);

    const actualDisabled = await createBtn.isDisabled();
    const screenshotPath = SCREENSHOTS + "/collection_" + tc.tag + ".png";
    await page.screenshot({ path: screenshotPath });
    console.log('Collection "' + tc.value + '" (' + tc.tag + "): disabled=" + actualDisabled + " expected=" + tc.expectDisabled);

    if (actualDisabled !== tc.expectDisabled) {
      logBug(
        "Create & Switch button state wrong for collection name: " + tc.tag,
        [
          "1. Open Settings tab",
          "2. Type \"" + tc.value + "\" in New Collection Name",
          "3. Observe button state",
        ],
        "Button should be " + (tc.expectDisabled ? "disabled" : "enabled"),
        "Button is " + (actualDisabled ? "disabled" : "enabled"),
        screenshotPath,
        "Medium"
      );
    }
  }

  // TEST 7: Inline validation message
  await collectionInput.click({ clickCount: 3 });
  await page.keyboard.type("ab_12");
  await page.waitForTimeout(250);
  const valMsgCount = await page.locator("text=Must be 6").count();
  await page.screenshot({ path: SCREENSHOTS + "/07_validation_msg.png" });
  if (!valMsgCount) {
    logBug(
      "No inline validation message for invalid collection name (5 chars)",
      ["1. Open Settings tab", "2. Type \"ab_12\" (5 chars) in New Collection Name"],
      'Inline error text: "Must be 6–20 characters, alphanumeric, underscore, or hyphen only"',
      "No validation message displayed",
      SCREENSHOTS + "/07_validation_msg.png",
      "Medium"
    );
  }

  // TEST 8: Active collection dropdown — 0 docs synthetic fallback
  const allOpts = await page.locator("#active-collection option").allTextContents();
  console.log("Collection dropdown options:", allOpts);

  const zeroDocs = allOpts.filter((o) => o.includes("(0 docs)"));
  const nonZero = allOpts.filter((o) => !o.includes("(0 docs)"));
  if (zeroDocs.length > 0) {
    // The active collection is shown with 0 docs. If this is because the
    // collections API didn't return it, the fallback entry uses count=0.
    logBug(
      "Active Collection dropdown shows current collection with \"(0 docs)\" — synthetic fallback count is always 0",
      [
        "1. Open Settings tab",
        "2. Observe Active Collection dropdown",
      ],
      "If the active collection has documents, dropdown should show the real document count",
      "Option(s) with \"(0 docs)\": " + zeroDocs.join(", ") +
        ". Code in SettingsPanel.tsx injects { name: config.collection_name, count: 0 } as a fallback, " +
        "so when the active collection is not returned by the /collections API it always shows 0 docs.",
      SCREENSHOTS + "/01_settings_initial.png",
      "Medium"
    );
  }

  // TEST 9: Save Settings feedback
  await collectionInput.click({ clickCount: 3 });
  await page.keyboard.press("Delete");
  const saveBtn = page.locator("button:has-text('Save Settings')");
  await saveBtn.click();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: SCREENSHOTS + "/08_after_save.png" });

  const msgInfo = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll("[class]")).filter(
      (el) => typeof el.className === "string" && (el.className.includes("bg-green") || el.className.includes("bg-red"))
    );
    return els.map((e) => ({ text: (e.textContent || "").trim(), cls: e.className }));
  });
  console.log("Feedback messages after save:", JSON.stringify(msgInfo));

  if (!msgInfo.length) {
    logBug(
      "No feedback message shown after Save Settings attempt",
      ["1. Open Settings tab", "2. Click Save Settings button"],
      "A success or error message should appear",
      "No feedback message rendered (checked for bg-green and bg-red class elements)",
      SCREENSHOTS + "/08_after_save.png",
      "High"
    );
  }

  // TEST 10: Message position relative to Save button
  if (msgInfo.length) {
    const posInfo = await page.evaluate(() => {
      const msgEl = Array.from(document.querySelectorAll("[class]")).find(
        (el) => typeof el.className === "string" && (el.className.includes("bg-green") || el.className.includes("bg-red"))
      );
      const saveEl = Array.from(document.querySelectorAll("button")).find((b) =>
        (b.textContent || "").includes("Save Settings")
      );
      if (!msgEl || !saveEl) return null;
      const mRect = msgEl.getBoundingClientRect();
      const sRect = saveEl.getBoundingClientRect();
      return {
        msgTop: Math.round(mRect.top),
        saveTop: Math.round(sRect.top),
        msgText: (msgEl.textContent || "").trim().slice(0, 50),
      };
    });
    console.log("Position info:", posInfo);
    if (posInfo && posInfo.msgTop > posInfo.saveTop) {
      logBug(
        "Feedback message appears below the Save Settings button",
        ["1. Open Settings tab", "2. Click Save Settings", "3. Observe layout"],
        "Message should appear above (before) the Save button in visual order",
        "Message (\"" + posInfo.msgText + "\") is at y=" + posInfo.msgTop +
          " which is below Save button at y=" + posInfo.saveTop,
        SCREENSHOTS + "/08_after_save.png",
        "Low"
      );
    }
  }

  // TEST 11: JavaScript console errors
  const jsErrors = consoleLogs.filter(
    (e) =>
      e.type === "error" &&
      !e.text.toLowerCase().includes("failed to fetch") &&
      !e.text.toLowerCase().includes("err_connection_refused") &&
      !e.text.toLowerCase().includes("404") &&
      !e.text.toLowerCase().includes("cors")
  );
  if (jsErrors.length > 0) {
    logBug(
      "Unexpected JavaScript console errors (" + jsErrors.length + " errors)",
      ["1. Open Settings tab", "2. Interact with controls"],
      "No JavaScript errors in console",
      jsErrors.slice(0, 3).map((e) => e.text).join(" | "),
      SCREENSHOTS + "/08_after_save.png",
      "Medium"
    );
  }

  await page.screenshot({ path: SCREENSHOTS + "/09_final.png", fullPage: true });
  await browser.close();

  console.log("\n=== CONSOLE LOG (errors/warnings) ===");
  consoleLogs
    .filter((l) => l.type === "error" || l.type === "warning")
    .forEach((l) => console.log("[" + l.type + "] " + l.text.slice(0, 160)));

  return bugs;
}

run()
  .then((bugs) => {
    console.log("\n\n========== BUGS FOUND: " + bugs.length + " ==========");
    console.log(JSON.stringify(bugs, null, 2));
  })
  .catch((err) => {
    console.error("FATAL:", err.message);
    console.error(err.stack);
    process.exit(1);
  });
