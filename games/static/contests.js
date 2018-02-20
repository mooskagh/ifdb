var CONTESTS = (function() {
  'use strict';
  function LayoutContestBoxes() {
    var left = 60;
    var right = 60;
    var min_width = 400;
    var max_step = 320;


    function doResize() {
      var cur_occupation = [];
      var working_set = [];

      function tryFlush(pos) {
        if (!cur_occupation) return;
        var total = cur_occupation.length;
        if (pos !== undefined) {
          for (var i = 1; i < total; ++i) {
            if (cur_occupation[i] > pos) return;
          }
        }

        var win_width = $(window).width() - right;
        if (win_width > left + max_step * total) {
          win_width = left + max_step * total;
        }
        if (win_width < min_width) {
          win_width = min_width;
        }
        for (var i = 0; i < total; ++i) {
          var offset = ((win_width - left) / total * i) + left;
          for (var j = 0; j < working_set[i].length; ++j) {
            working_set[i][j].css('left', offset);
          }
        }

        if (pos !== undefined && cur_occupation[0] > pos) {
          cur_occupation.length = 1;
          working_set = [[]];
        } else {
          cur_occupation = [];
          working_set = [];
        }
      }

      $('.contest-box').each(function(i, e) {
        var el = $(e);
        var top = el.position().top;
        var height = el.height();
        tryFlush(top);
        for (var i = 0; i < cur_occupation.length; ++i) {
          if (top >= cur_occupation[i]) break;
        }
        if (i == cur_occupation.length) {
          cur_occupation.push(0);
          working_set.push([]);
        }
        cur_occupation[i] = top + height;
        working_set[i].push(el);
      });
      tryFlush();
    }
    $(window).resize(doResize);
    doResize();
  }

  return {LayoutContestBoxes: LayoutContestBoxes};
})();