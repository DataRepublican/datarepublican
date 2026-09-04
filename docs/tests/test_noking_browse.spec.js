const { test, expect } = require("@playwright/test");

test("browse_index_html loads correctly", async ({ page }) => {
  const response = await page.goto(
    `${process.env.HOST || "http://localhost:4000"}/browse/index.html`
  );
  expect(response.status()).toBe(200);
  await expect(page).toHaveTitle(/.+/);
  // Add more assertions here (e.g., await expect(page.locator('h1')).toBeVisible());
});

import { test, expect } from "@playwright/test";

test("test", async ({ page }) => {
  await page.goto(
    `${process.env.HOST || "http://localhost:4000"}/nokings/index.html`
  );
  await page.getByRole("link", { name: "Explore Top" }).click();
  await expect(page.locator("#loading")).toBeVisible();
  await page.goto(
    "https://60.datarepublican.com/browse/?e=113269182%7E1%7E1&e=131644147%7E1%7E1&e=132630359%7E1%7E1&e=132644641%7E1%7E1&e=132758558%7E1%7E2&e=133065716%7E1%7E1&e=133109557%7E1%7E1&e=133191113%7E1%7E2&e=133442022%7E1%7E1&e=133539048%7E1%7E2&e=133584089%7E1%7E0&e=133871360%7E1%7E1&e=134188834%7E1%7E2&e=135582895%7E1%7E0&e=136213516%7E1%7E4&e=202389388%7E1%7E0&e=204448446%7E1%7E0&e=204465717%7E1%7E0&e=204496889%7E1%7E0&e=204994004%7E2%7E1&e=205806345%7E1%7E1&e=222010593%7E1%7E0&e=237059731%7E1%7E0&e=237104508%7E1%7E1&e=237122879%7E1%7E1&e=237137105%7E1%7E0&e=237420660%7E1%7E1&e=261150699%7E1%7E1&e=261270198%7E1%7E0&e=262369596%7E1%7E1&e=264680984%7E1%7E0&e=270061100%7E1%7E1&e=270193587%7E1%7E1&e=270321696%7E1%7E1&e=271847561%7E1%7E0&e=273943866%7E1%7E1&e=274329476%7E1%7E0&e=300037131%7E1%7E1&e=320160439%7E1%7E0&e=320512546%7E1%7E1&e=341230337%7E1%7E0&e=362755109%7E1%7E1&e=362969526%7E1%7E1&e=370989990%7E1%7E1&e=371430158%7E1%7E1&e=391302520%7E1%7E1&e=411322686%7E1%7E1&e=436070952%7E1%7E0&e=450709993%7E1%7E1&e=453860271%7E1%7E1&e=455569879%7E1%7E0&e=460639645%7E1%7E1&e=462525580%7E1%7E1&e=464605470%7E1%7E1&e=464773036%7E1%7E0&e=465216666%7E1%7E0&e=465499822%7E1%7E0&e=474418013%7E1%7E0&e=475180376%7E1%7E1&e=475518278%7E1%7E0&e=520880625%7E1%7E1&e=521213010%7E1%7E1&e=521243457%7E1%7E1&e=521263996%7E1%7E1&e=521332694%7E1%7E1&e=521499111%7E1%7E0&e=521541501%7E1%7E0&e=521554826%7E1%7E0&e=521733698%7E1%7E3&e=521865575%7E1%7E1&e=522210858%7E1%7E1&e=526078441%7E1%7E1&e=530184647%7E1%7E0&e=530196605%7E1%7E0&e=530239013%7E1%7E1&e=541426440%7E1%7E1&e=760343171%7E1%7E1&e=810587332%7E1%7E0&e=812081153%7E1%7E0&e=813260391%7E1%7E0&e=813625061%7E1%7E1&e=814571869%7E1%7E0&e=814944067%7E2%7E1&e=821232167%7E1%7E1&e=822355901%7E1%7E1&e=822543434%7E1%7E1&e=823835203%7E1%7E1&e=824589218%7E1%7E0&e=834158350%7E1%7E0&e=844535961%7E1%7E1&e=850692228%7E1%7E0&e=870439810%7E1%7E0&e=871262978%7E1%7E0&e=874298762%7E1%7E0&e=880776955%7E1%7E0&e=900018359%7E1%7E0&e=911982332%7E1%7E0&e=941153307%7E1%7E1&e=943213100%7E1%7E1&e=946168317%7E1%7E1&s=3&X=2&Y=2"
  );
  await expect(page.locator("#graph")).toBeVisible();
  await page.getByRole("button", { name: "Show Presets" }).click();
  await page.locator("#ngo-popup label").click();
  await page.getByRole("button", { name: "Climate Grift" }).click();
  await expect(
    page.getByText("Cooperative For Assistance And Relief", { exact: true })
  ).toBeVisible();
  await page.getByRole("button", { name: "Show Presets" }).click();
  await page.getByRole("button", { name: "Clinton" }).click();
  await page.getByRole("button", { name: "Fit to Screen" }).click();
  await page.getByRole("button", { name: "Expand Layout H" }).click();
  await page.getByRole("button", { name: "Shrink Layout H" }).click();
  await page.getByRole("button", { name: "Expand Layout H" }).click();
  await page.getByRole("button", { name: "Expand Layout H" }).click();
  await page.getByRole("button", { name: "Reset Layout Scale H" }).click();
  await page.getByRole("button", { name: "Expand Layout H" }).click();
  await page.getByRole("button", { name: "Expand Layout H" }).click();
  await page.getByRole("button", { name: "Expand Flows" }).click();
  await page.getByRole("button", { name: "Compact Flows" }).click();
  await page.getByRole("button", { name: "Default Flows (3)" }).click();
  await page.getByRole("button", { name: "Expand Layout V" }).click();
  await page.getByRole("button", { name: "Expand Layout V" }).click();
  await page.getByRole("button", { name: "Shrink Layout V" }).click();
  await page
    .getByRole("button", { name: "Reset Layout Scale", exact: true })
    .click();
  await page.getByRole("button", { name: "Expand Layout H" }).click();
});
