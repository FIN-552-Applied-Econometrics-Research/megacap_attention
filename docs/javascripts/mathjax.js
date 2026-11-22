window.MathJax = {
  tex: {
    inlineMath: [["\(", "\)"]],
    displayMath: [["\[", "\]"]],
    processEscapes: true,
    processEnvironments: true,
    macros: { CAR: "\mathit{CAR}", SUE: "\mathit{SUE}", MegaDay: "\mathit{MegaDay}" }
  },
  options: { ignoreHtmlClass: ".*|", processHtmlClass: "arithmatex" }
};
document$.subscribe(() => {
  MathJax.startup.output.clearCache();
  MathJax.typesetClear();
  MathJax.texReset();
  MathJax.typesetPromise();
});
