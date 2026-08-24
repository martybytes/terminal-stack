/* Run inside the shared Playwright Docker container after deployment. */
const { chromium } = require("playwright");

(async () => {
  const baseUrl = process.env.AGENT007_URL || "http://host.docker.internal:3114";
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH,
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1000 } });
  const errors = [];
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  page.on("pageerror", (error) => errors.push(error.message));

  const forceReadableRange = (economics) => ({
    ...economics,
    modeledRetrievals: 4,
    estimatedAvoidedTokensLow: 3_810_000,
    estimatedAvoidedTokensHigh: 5_090_000,
  });
  await page.route("**/api/memory-effectiveness/history", async (route) => {
    const now = Date.now();
    const window = (from, low, high, modeledRetrievals) => ({
      from, to: now, estimatedAvoidedTokensLow: low, estimatedAvoidedTokensHigh: high,
      modeledRetrievals, legacyEstimateCount: modeledRetrievals,
    });
    await route.fulfill({ json: {
      generatedAt: now,
      trackingSince: now - 30 * 86_400_000,
      past24Hours: window(now - 86_400_000, 44_300_000, 59_100_000, 24),
      past7Days: window(now - 7 * 86_400_000, 312_000_000, 416_000_000, 168),
      allTracked: window(now - 30 * 86_400_000, 1_200_000_000, 1_600_000_000, 720),
    } });
  });
  await page.route("**/api/memory-effectiveness", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.economics = forceReadableRange(body.economics);
    await route.fulfill({ response, json: body });
  });
  await page.route("**/api/projects", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.projects = (body.projects ?? []).map((project) => ({
      ...project,
      economics: forceReadableRange(project.economics),
    }));
    await route.fulfill({ response, json: body });
  });
  const readableOverflow = () => page.locator("[data-readable-text]").evaluateAll((elements) => elements
    .filter((element) => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1)
    .map((element) => ({
      text: (element.textContent ?? "").trim(),
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    })));

  await page.goto(`${baseUrl}/#/overview`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => {
    localStorage.removeItem("agent007memory.preferences.v1");
    localStorage.removeItem("agent007memory.sidebar.collapsed");
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator("[data-testid=overview-page]").waitFor();
  await page.locator("[data-testid=memory-effectiveness]").waitFor();

  const main = page.locator("main > div").first();
  const dimensions = await main.evaluate((element) => ({ client: element.clientHeight, scroll: element.scrollHeight }));
  const cards = await page.locator("[data-testid=overview-projects] a").count();
  const projectSignals = await page.locator("[data-testid=overview-projects]").innerText();
  const overviewText = await page.locator("main").innerText();
  const overviewCostHidden = !/API cost|Billed\s*·?\s*MTD/i.test(overviewText);
  const expandedReadableOverflow = await readableOverflow();
  const compactRangesVisible = (overviewText.match(/3\.8–5\.1M/g) ?? []).length >= 2;
  const historyWindowsVisible = /44\.3–59\.1M/.test(overviewText) && /312–416M/.test(overviewText) && /1\.2–1\.6G/.test(overviewText);
  const avoidedLabel = page.getByText("Context avoided", { exact: true }).first();
  const avoidedLabelLayout = await avoidedLabel.locator("..").evaluate((element) => ({
    whiteSpace: getComputedStyle(element).whiteSpace,
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  await avoidedLabel.hover();
  const contextualTooltip = page.getByRole("tooltip");
  await contextualTooltip.waitFor();
  const tooltipSurface = await contextualTooltip.evaluate((element) => ({
    backgroundColor: getComputedStyle(element).backgroundColor,
    opacity: getComputedStyle(element).opacity,
  }));
  await page.mouse.move(10, 10);
  await page.getByTestId("sidebar-toggle").click();
  const collapsedReadableOverflow = await readableOverflow();
  const collapsedDimensions = await main.evaluate((element) => ({ client: element.clientHeight, scroll: element.scrollHeight }));
  await page.screenshot({ path: "/tmp/agent007-overview-dark.png", fullPage: false });

  await page.getByTestId("customize-page").click();
  const drawer = page.getByRole("dialog");
  await drawer.waitFor();
  await drawer.getByRole("button", { name: "light", exact: true }).click();
  const lightReadableOverflow = await readableOverflow();
  await drawer.locator("select").first().selectOption("focused");
  const memoryRow = drawer.locator("div.rounded-xl").filter({ hasText: "Memory flow" }).first();
  await memoryRow.locator("button[aria-pressed]").first().click();
  const saved = await page.evaluate(() => localStorage.getItem("agent007memory.preferences.v1"));
  await page.getByRole("button", { name: "Close customizer" }).click();
  await page.reload({ waitUntil: "domcontentloaded" });
  const persisted = {
    theme: await page.evaluate(() => document.documentElement.dataset.theme),
    memoryHidden: await page.locator("[data-testid=memory-effectiveness]").count() === 0,
    width: await page.locator(".page-canvas").evaluate((element) => getComputedStyle(element).maxWidth),
  };
  await page.screenshot({ path: "/tmp/agent007-overview-light.png", fullPage: false });

  await page.goto(`${baseUrl}/#/requests`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("customize-page").click();
  const requestDrawer = page.getByRole("dialog");
  await requestDrawer.getByText("Method", { exact: true }).locator("..").locator("button[aria-pressed]").click();
  await page.getByRole("button", { name: "Close customizer" }).click();
  const methodHidden = await page.getByRole("columnheader", { name: "Method", exact: true }).count() === 0;

  await page.goto(`${baseUrl}/#/llm`, { waitUntil: "domcontentloaded" });
  await page.getByText("LOCAL · NO API FEES", { exact: true }).waitFor();
  const exactCalls = page.getByTestId("exact-provider-calls");
  await exactCalls.waitFor();
  const exactCallsLayout = await exactCalls.evaluate((element) => ({
    isLastSection: element.parentElement?.lastElementChild === element,
    title: element.querySelector("div")?.textContent ?? "",
  }));
  const exactCallsWindow = page.getByTestId("exact-provider-calls-window");
  const exactCallsScroll = await exactCallsWindow.count() ? await exactCallsWindow.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      maxHeight: style.maxHeight,
      overflowY: style.overflowY,
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    };
  }) : null;
  const rangeText = (await exactCalls.locator("span.font-mono").last().textContent()) ?? "";
  const rangeMatch = rangeText.match(/([\d,]+)–([\d,]+) of ([\d,]+)/);
  const shownCalls = rangeMatch ? Number(rangeMatch[2].replaceAll(",", "")) : 0;
  const retainedCalls = rangeMatch ? Number(rangeMatch[3].replaceAll(",", "")) : 0;
  const nextPage = exactCalls.getByRole("button", { name: "Next page" });
  const paginationValid = retainedCalls <= shownCalls || !(await nextPage.isDisabled());
  if (retainedCalls > shownCalls) {
    await nextPage.click();
    await exactCalls.getByRole("button", { name: "Previous page" }).click();
  }
  await exactCalls.getByRole("button", { name: "Learn about Exact provider calls" }).click();
  await page.getByRole("dialog", { name: "Exact provider calls" }).waitFor();
  await page.keyboard.press("Escape");
  const localLlm = {
    paidCostHidden: await page.getByText("Paid provider cost", { exact: true }).count() === 0,
    keysHidden: await page.locator("[data-testid=openai-key-hints]").count() === 0,
    estimatedCostColumnHidden: await page.getByRole("columnheader", { name: "Est. cost", exact: true }).count() === 0,
    outputRateVisible: await page.getByRole("columnheader", { name: "Output rate", exact: true }).count() === 1,
  };
  await page.screenshot({ path: "/tmp/agent007-llm-local.png", fullPage: false });
  await page.evaluate(() => localStorage.removeItem("agent007memory.preferences.v1"));

  const result = {
    dimensions,
    fitsDefaultOverview: dimensions.scroll <= dimensions.client + 1,
    cards,
    hasSaved: /saved/i.test(projectSignals),
    hasRecall: /recall/i.test(projectSignals),
    hasDurable: /durable knowledge/i.test(overviewText),
    overviewCostHidden,
    compactRangesVisible,
    historyWindowsVisible,
    expandedReadableOverflow,
    collapsedReadableOverflow,
    collapsedDimensions,
    lightReadableOverflow,
    avoidedLabelLayout,
    tooltipSurface,
    storedPreference: Boolean(saved),
    persisted,
    methodHidden,
    localLlm,
    exactCallsLayout,
    exactCallsScroll,
    paginationValid,
    errors,
  };
  console.log(JSON.stringify(result, null, 2));
  await browser.close();
  const tooltipOpaque = result.tooltipSurface.opacity === "1" && !/rgba\([^)]*,\s*0(?:\.0+)?\)/.test(result.tooltipSurface.backgroundColor);
  const labelReadable = result.avoidedLabelLayout.whiteSpace !== "nowrap" && result.avoidedLabelLayout.scrollHeight <= result.avoidedLabelLayout.clientHeight + 1;
  if (!result.fitsDefaultOverview || result.collapsedDimensions.scroll > result.collapsedDimensions.client + 1 || !result.compactRangesVisible || !result.historyWindowsVisible || result.expandedReadableOverflow.length || result.collapsedReadableOverflow.length || result.lightReadableOverflow.length || !result.hasSaved || !result.hasRecall || !result.hasDurable || !result.overviewCostHidden || !labelReadable || !tooltipOpaque || !result.storedPreference || result.persisted.theme !== "light" || !result.persisted.memoryHidden || !result.methodHidden || !result.localLlm.paidCostHidden || !result.localLlm.keysHidden || !result.localLlm.estimatedCostColumnHidden || !result.localLlm.outputRateVisible || !result.exactCallsLayout.isLastSection || !result.paginationValid || (result.exactCallsScroll && (result.exactCallsScroll.overflowY !== "auto" || Number.parseInt(result.exactCallsScroll.maxHeight, 10) > 360)) || result.errors.length) process.exitCode = 1;
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
