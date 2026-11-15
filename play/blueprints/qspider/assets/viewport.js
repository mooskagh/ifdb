(function () {
  var STORAGE_KEY = "qspider-pause-button-offset";
  var PAUSE_ICON_SVG =
    '<svg width="15" height="15" viewBox="0 0 15 15" fill="none" xmlns="http://www.w3.org/2000/svg">' +
    '<path d="M6.04995 2.74998C6.04995 2.44623 5.80371 2.19998 5.49995 2.19998C5.19619 2.19998 4.94995 2.44623 4.94995 2.74998V12.25C4.94995 12.5537 5.19619 12.8 5.49995 12.8C5.80371 12.8 6.04995 12.5537 6.04995 12.25V2.74998ZM10.05 2.74998C10.05 2.44623 9.8037 2.19998 9.5 2.19998C9.1962 2.19998 8.95 2.44623 8.95 2.74998V12.25C8.95 12.5537 9.1962 12.8 9.5 12.8C9.8037 12.8 10.05 12.5537 10.05 12.25V2.74998Z" fill="currentColor" fill-rule="evenodd" clip-rule="evenodd"></path>' +
    "</svg>";

  function isTouchDevice() {
    return (
      "ontouchstart" in window ||
      navigator.maxTouchPoints > 0 ||
      ("msMaxTouchPoints" in navigator && navigator.msMaxTouchPoints > 0)
    );
  }

  if (!isTouchDevice()) {
    return;
  }

  function getStoredOffset() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      var parsed = raw !== null ? Number(JSON.parse(raw)) : 0;
      return Number.isFinite(parsed) ? parsed : 0;
    } catch (e) {
      return 0;
    }
  }

  function setStoredOffset(value) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    } catch (e) {}
  }

  var offset = getStoredOffset();
  var isDragging = false;
  var startTouch = 0;

  var container = document.createElement("div");
  container.className = "qsp-touch-pause-button";

  var button = document.createElement("button");
  button.type = "button";
  button.innerHTML = PAUSE_ICON_SVG;
  button.style.transform = "translateX(" + offset + "px)";
  container.appendChild(button);

  button.addEventListener(
    "touchstart",
    function (e) {
      if (!e.touches || !e.touches.length) {
        return;
      }
      startTouch = e.touches[0].clientX - (offset || 0);
      isDragging = true;
    },
    { passive: true }
  );

  function onTouchMove(e) {
    if (!isDragging || !e.touches || !e.touches.length) {
      return;
    }
    offset = e.touches[0].clientX - startTouch;
    button.style.transform = "translateX(" + offset + "px)";
    setStoredOffset(offset);
  }

  button.addEventListener("touchmove", onTouchMove, { passive: true });
  window.addEventListener("touchmove", onTouchMove, { passive: true });

  window.addEventListener(
    "touchend",
    function () {
      if (!isDragging) {
        return;
      }
      isDragging = false;
    },
    { passive: true }
  );

  button.addEventListener("click", function () {
    var portal = document.getElementById("portal-container");
    if (
      (portal && portal.children.length > 0) ||
      document.querySelector(".wait-lock")
    ) {
      return;
    }
    document.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Escape",
        code: "Escape",
        keyCode: 27,
        which: 27,
        bubbles: true,
        cancelable: true,
      })
    );
  });

  function mountIfNeeded() {
    var gameRoot = document.querySelector("qsp-game-root");
    if (gameRoot && !gameRoot.contains(container)) {
      gameRoot.appendChild(container);
    }
  }

  var root = document.getElementById("root") || document.body;
  if (root) {
    new MutationObserver(mountIfNeeded).observe(root, {
      childList: true,
      subtree: true,
    });
  }
  mountIfNeeded();
})();
