(function () {
  'use strict';
  var contents = document.querySelector('[data-collection-contents]');
  if (!contents) return;
  var mobile = window.matchMedia('(max-width: 767px)');
  function layout() { contents.open = !mobile.matches; }
  layout();
  mobile.addEventListener('change', layout);
  contents.addEventListener('click', function (event) {
    if (mobile.matches && event.target.closest('a[href^="#solution-"]')) contents.open = false;
  });
  // Keep an initial deep link aligned after mathematics and images settle.
  var initialHash = window.location.hash;
  if (initialHash.startsWith('#solution-')) {
    Promise.resolve(window.asterProofSharedMathReady).then(function () {
      if (window.location.hash !== initialHash) return;
      var target = document.getElementById(initialHash.slice(1));
      if (target) target.scrollIntoView();
    });
  }
})();
