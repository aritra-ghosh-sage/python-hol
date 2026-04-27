import { test, expect } from '@playwright/test';
import fs from 'fs';

test('chat persistence scenarios A-D', async ({ page }) => {
  const out = {
    backend_start: { status: 'pass', details: '' },
    frontend_start: { status: 'pass', details: '' },
    scenarios: {
      A: { status: 'blocked', details: '' },
      B: { status: 'blocked', details: '' },
      C: { status: 'blocked', details: '' },
      D: { status: 'blocked', details: '' },
    },
    evidence: [],
    errors: [],
  };

  try {
    await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(1200);

    const navLabels = await page.locator('aside button span').allTextContents();
    out.evidence.push(`nav_labels=${JSON.stringify(navLabels)}`);

    const statusLocator = page.locator('main span.text-sm.text-gray-400').first();
    const statusInitial = await statusLocator.textContent().catch(() => null);
    out.evidence.push(`status_initial=${statusInitial}`);

    let connected = false;
    try {
      await page.waitForFunction(() => {
        return Array.from(document.querySelectorAll('main span')).some((s) => (s.textContent || '').trim() === 'Connected');
      }, { timeout: 30000 });
      connected = true;
    } catch {}

    const statusAfter = await statusLocator.textContent().catch(() => null);
    out.evidence.push(`status_after_wait=${statusAfter}`);

    const m1 = `E2E-M1-${Date.now()}`;
    const m2 = `E2E-M2-${Date.now()}`;

    if (!connected) {
      out.scenarios.A = { status: 'blocked', details: 'WebSocket never reached Connected.' };
      out.scenarios.B = { status: 'blocked', details: 'Input remained disabled.' };
      out.scenarios.C = { status: 'blocked', details: 'Input remained disabled.' };
      out.scenarios.D = { status: 'blocked', details: 'No message available for reload validation.' };
    } else {
      const input = page.locator('textarea[placeholder*="Ask a question"]').first();
      await expect(input).toBeVisible();
      await expect(input).toBeEnabled({ timeout: 15000 });

      await input.fill(m1);
      await input.press('Enter');
      await expect(page.getByText(m1)).toBeVisible({ timeout: 20000 });
      out.evidence.push(`m1_visible=true value=${m1}`);

      const switchTarget = page.locator('aside button span').filter({ hasText: /Add Data|Settings|Documents|Knowledge|Ingest/i }).first();
      if (await switchTarget.count()) {
        const label = (await switchTarget.textContent())?.trim() || '';
        await switchTarget.click();
        await page.waitForTimeout(600);
        await page.locator('aside button span', { hasText: /^Query$/i }).first().click();
        await page.waitForTimeout(600);
        const m1Count = await page.getByText(m1).count();
        out.scenarios.A = { status: m1Count > 0 ? 'pass' : 'fail', details: `switched_to=${label} m1_count_after_return=${m1Count}` };
      } else {
        out.scenarios.A = { status: 'blocked', details: `No alternate panel found. nav_labels=${JSON.stringify(navLabels)}` };
      }

      const clearBtn = page.getByRole('button', { name: /Clear history|Clear chat history/i }).first();
      await clearBtn.click();
      await page.waitForTimeout(700);
      const m1AfterClear = await page.getByText(m1).count();
      const clearDisabled = await clearBtn.isDisabled();
      out.scenarios.B = {
        status: m1AfterClear === 0 && clearDisabled ? 'pass' : 'fail',
        details: `m1_count_after_clear=${m1AfterClear} clear_disabled=${clearDisabled}`,
      };

      await expect(input).toBeEnabled({ timeout: 10000 });
      await input.fill(m2);
      await input.press('Enter');
      await expect(page.getByText(m2)).toBeVisible({ timeout: 20000 });
      const m2Count = await page.getByText(m2).count();
      out.scenarios.C = { status: m2Count > 0 ? 'pass' : 'fail', details: `m2_count_after_send=${m2Count}` };

      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1200);
      const m2AfterReload = await page.getByText(m2).count();
      out.scenarios.D = { status: m2AfterReload > 0 ? 'pass' : 'fail', details: `m2_count_after_reload=${m2AfterReload}` };

      const storageMeta = await page.evaluate(() => {
        const raw = localStorage.getItem('chat-history-v1');
        let parseable = false;
        let count = null;
        if (raw) {
          try {
            const parsed = JSON.parse(raw);
            parseable = true;
            count = parsed?.state?.messages?.length ?? null;
          } catch {}
        }
        return { exists: raw !== null, length: raw ? raw.length : 0, parseable, messageCount: count };
      });
      out.evidence.push(`localStorage_chat-history-v1=${JSON.stringify(storageMeta)}`);
    }
  } catch (e) {
    out.errors.push(String(e && e.stack ? e.stack : e));
  }

  fs.writeFileSync('/tmp/e2e_chat_result.json', JSON.stringify(out));
  console.log('E2E_RESULT=' + JSON.stringify(out));
});
