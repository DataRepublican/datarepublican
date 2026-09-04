globalThis.window = globalThis;
globalThis.window.d3 = {
  max: (arr, acc) => {
    const vals = acc ? arr.map(acc) : arr;
    return Math.max(...vals.filter((x) => x != null && Number.isFinite(x)));
  },
  cubehelix: () => ({ toString: () => "#888" }),
};
globalThis.history = {
  replaceState() {},
};
if (!globalThis.location) {
  globalThis.location = { pathname: "/browse/", search: "" };
}
globalThis.$ = () => ({
  html() {},
  text() {},
  show() {},
  hide() {},
  addClass() {},
  removeClass() {},
});
