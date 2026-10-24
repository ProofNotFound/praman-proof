/**
 * Record a 1920x1080 video of the 4 demo cases in present mode at 1x speed.
 * Uses global Playwright on macOS.
 *
 * Usage:
 *   NODE_PATH=/opt/homebrew/lib/node_modules node scripts/record_demo.cjs
 */

const { chromium } = require('/opt/homebrew/lib/node_modules/playwright');
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');

const ROOT_DIR = path.resolve(__dirname, '..');
const DEMO_DIR = path.resolve(ROOT_DIR, 'demo-video');
const PORT = 4173;
const BASE_URL = `http://127.0.0.1:${PORT}`;

if (!fs.existsSync(DEMO_DIR)) {
  fs.mkdirSync(DEMO_DIR, { recursive: true });
}

function waitForServer(url, timeoutMs = 20000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    function check() {
      http
        .get(url, (res) => {
          if (res.statusCode === 200) {
            resolve();
          } else {
            retry();
          }
        })
        .on('error', retry);
    }
    function retry() {
      if (Date.now() - start > timeoutMs) {
        return reject(new Error(`Server at ${url} did not respond within ${timeoutMs}ms`));
      }
      setTimeout(check, 300);
    }
    check();
  });
}

async function main() {
  console.log('1. Starting preview server on port', PORT);
  const server = spawn('npx', ['vite', 'preview', '--port', String(PORT), '--strictPort'], {
    cwd: path.resolve(ROOT_DIR, 'frontend'),
    stdio: 'inherit',
  });

  const cleanup = () => {
    try {
      server.kill();
    } catch {}
  };
  process.on('exit', cleanup);
  process.on('SIGINT', cleanup);
  process.on('SIGTERM', cleanup);

  try {
    await waitForServer(`${BASE_URL}/`);
    console.log('2. Preview server is ready at', BASE_URL);

    console.log('3. Launching Chromium with 1920x1080 video recording...');
    const browser = await chromium.launch({
      headless: true,
    });

    const context = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
      recordVideo: {
        dir: DEMO_DIR,
        size: { width: 1920, height: 1080 },
      },
    });

    const page = await context.newPage();

    console.log('4. Navigating to intake screen...');
    await page.goto(`${BASE_URL}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);

    // Turn on present mode with 'P'
    console.log('   Enabling Present mode (P)...');
    await page.keyboard.press('p');
    await page.waitForTimeout(2000);

    // Helper to wait until case playback finishes
    const waitForPlaybackDone = async (caseName, maxMs = 90000) => {
      console.log(`   Waiting for ${caseName} playback to complete (timeout: ${maxMs}ms)...`);
      await page.waitForFunction(
        () => {
          const bar = document.querySelector('.ticks[role="progressbar"]');
          if (!bar) return false;
          const now = parseInt(bar.getAttribute('aria-valuenow') || '0', 10);
          const max = parseInt(bar.getAttribute('aria-valuemax') || '0', 10);
          return max > 0 && now >= max;
        },
        undefined,
        { timeout: maxMs }
      );
      console.log(`   ✓ ${caseName} playback completed!`);
    };

    // Case 1: L14
    console.log('5. Case 1: L14 (Compostable Garbage Bags)');
    await page.keyboard.press('1');
    await page.waitForURL('**/case/L14.agent', { timeout: 10000 });
    await page.waitForTimeout(1500); // Linger on initial paused state
    console.log('   Resuming playback with Space...');
    await page.keyboard.press('Space');
    await waitForPlaybackDone('L14', 60000);
    await page.waitForTimeout(3000); // Linger on final verdicts

    // Compare mode
    console.log('   Showing Compare mode (B)...');
    await page.keyboard.press('b');
    await page.waitForTimeout(3500);
    console.log('   Closing Compare mode (B)...');
    await page.keyboard.press('b');
    await page.waitForTimeout(1500);

    // Case 2: L06
    console.log('6. Case 2: L06 (Oxo-Biodegradable Bags)');
    await page.keyboard.press('2');
    await page.waitForURL('**/case/L06.agent', { timeout: 10000 });
    await page.waitForTimeout(1500);
    console.log('   Resuming playback with Space...');
    await page.keyboard.press('Space');
    await waitForPlaybackDone('L06', 45000);
    await page.waitForTimeout(3000);

    // Case 3: L08
    console.log('7. Case 3: L08 (Bamboo Toothbrush)');
    await page.keyboard.press('3');
    await page.waitForURL('**/case/L08.agent', { timeout: 10000 });
    await page.waitForTimeout(1500);
    console.log('   Resuming playback with Space...');
    await page.keyboard.press('Space');
    await waitForPlaybackDone('L08', 100000);
    await page.waitForTimeout(3000);

    // Case 4: L21
    console.log('8. Case 4: L21 (Educational Non-Claim)');
    await page.keyboard.press('4');
    await page.waitForURL('**/case/L21.agent', { timeout: 10000 });
    await page.waitForTimeout(1500);
    console.log('   Resuming playback with Space...');
    await page.keyboard.press('Space');
    await waitForPlaybackDone('L21', 20000);
    await page.waitForTimeout(3000);

    // Store Scan
    console.log('9. Navigating to Store Scan (/scan)...');
    await page.goto(`${BASE_URL}/scan`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(5000);

    console.log('10. Finalizing video recording...');
    const videoObj = page.video();
    await page.close();
    await context.close();
    await browser.close();

    if (videoObj) {
      const videoPath = await videoObj.path();
      const finalPath = path.resolve(DEMO_DIR, 'praman_demo_1080p.webm');
      fs.copyFileSync(videoPath, finalPath);
      console.log(`Video saved to: ${finalPath}`);
    }

    console.log('Demo recording successfully finished!');
  } finally {
    cleanup();
  }
}

main().catch((err) => {
  console.error('Error during demo recording:', err);
  process.exit(1);
});
