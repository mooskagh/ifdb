var CONTESTS = (function() {
  'use strict';
  function LayoutContestBoxes() {
    var left = 60;
    var right = 60;
    var min_width = 400;
    var card_width = 320;
    var gap = 20;
    var minimum_presence = 20;
    var minimum_month = 20;

    function doResize() {
      var columns = Math.floor(($(window).width() - right - left) / card_width);
      if (columns < 1) columns = 1;
      var end_days = new Array(columns).fill(0);

      var contests = $('.contest-box');
      var cur_contest = 0;

      var cur_day = 0;
      var cur_pixel = 0;
      var calm_ruler = [];
      $('.ruler-item').each(function(i, e) {
        var next_day = cur_day + parseInt($(e).attr('section-days'));

        var best_val = 0;
        var first = undefined;
        while (cur_contest < contests.length &&
               parseInt($(contests[cur_contest]).attr('top-days')) < next_day) {
          var contest = $(contests[cur_contest]);
          ++cur_contest;
          best_val = end_days[0] + 1;
          var best_idx = 0;
          var first_fit = columns;
          for (var i = columns - 1; i >= 0; --i) {
            if (end_days[i] < best_val) {
              best_val = end_days[i];
              best_idx = i;
            }
            if (end_days[i] <= cur_pixel) first_fit = i;
          }
          if (first_fit < columns) best_idx = first_fit;
          if (best_val < cur_pixel) best_val = cur_pixel;
          if (first === undefined) first = best_val;
          contest.css('top', best_val)
              .css('left', left + best_idx * card_width);
          end_days[best_idx] = best_val + gap + contest.height();
        }

        if (calm_ruler.length != 0 && first !== undefined) {
          var total_px = first - calm_ruler[0].position().top;
          for (var i = 0; i < calm_ruler.length; ++i) {
            var old = calm_ruler[i].height();
            var should_be = total_px / (calm_ruler.length - i);
            if (old < should_be) {
              calm_ruler[i].css('height', should_be);
              total_px -= should_be;
              cur_pixel += should_be - old;
            } else {
              total_px -= old;
            }
          }
          calm_ruler = [];
        }
        calm_ruler.push($(e));

        var height = best_val - cur_pixel + minimum_presence;
        if (height < minimum_month) height = minimum_month;

        $(e).css('height', height);
        cur_day = next_day;
        cur_pixel += height;
      });
      $('.contests-container').css('height', cur_pixel);
    }


    function doResize2() {
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