(function () {
  var canvas = document.getElementById("canvas");
  var container = document.querySelector(".emscripten_border");

  function fitCanvas() {
    var width = container.clientWidth;
    var height = container.clientHeight;
    if (!width || !height || !canvas.width || !canvas.height) {
      return;
    }
    var scale = Math.min(
      width / canvas.width,
      height / canvas.height
    );
    canvas.style.setProperty(
      "width",
      Math.round(canvas.width * scale) + "px",
      "important"
    );
    canvas.style.setProperty(
      "height",
      Math.round(canvas.height * scale) + "px",
      "important"
    );
  }

  window.addEventListener("resize", fitCanvas);
  window.addEventListener("load", fitCanvas);
  new ResizeObserver(fitCanvas).observe(container);
  Module.postRun.push(fitCanvas);
  fitCanvas();
})();
