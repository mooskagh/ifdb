(function () {
  function fit() {
    var container = document.getElementById("stead-container");
    if (!container) {
      return;
    }
    var width = container.offsetWidth;
    var height = container.offsetHeight;
    if (!width || !height) {
      return;
    }
    var winWidth = window.innerWidth;
    var winHeight = window.innerHeight;
    var scale = Math.min(winWidth / width, winHeight / height);
    container.style.transform = "scale(" + scale + ")";
  }

  window.addEventListener("resize", fit);
  window.addEventListener("load", fit);

  var observer = new MutationObserver(function () {
    var container = document.getElementById("stead-container");
    if (container) {
      fit();
      if (!container._viewportObserved) {
        container._viewportObserved = true;
        if (window.ResizeObserver) {
          new ResizeObserver(fit).observe(container);
        }
      }
    }
  });

  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  } else {
    document.addEventListener("DOMContentLoaded", function () {
      observer.observe(document.body, { childList: true, subtree: true });
    });
  }

  if (window.ResizeObserver) {
    new ResizeObserver(fit).observe(document.documentElement);
  }

  fit();
})();
