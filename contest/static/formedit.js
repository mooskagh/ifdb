var FORMEDIT = (function() {
  'use strict';

  var re = new RegExp('__prefix__', 'gs');

  function Adder(prefix) {
    $('.form-empty-' + prefix).hide();
    $('.form-addbutton-' + prefix).click(function() {
      var html = $('.form-empty-' + prefix).html();
      var total = $('#id_' + prefix + '-TOTAL_FORMS').attr('value');
      html = html.replace(re, total);
      $('.form-content-' + prefix).append($('<tr>').append(html));
      $('#id_' + prefix + '-TOTAL_FORMS')
          .attr('value', parseInt(total, 10) + 1);
    });
  }

  var res = {};
  res.Adder = Adder;
  return res;
}());