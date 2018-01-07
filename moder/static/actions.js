$(function() {
  "use strict";

  function GetCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      var cookies = document.cookie.split(';');
      for (var i = 0; i < cookies.length; i++) {
        var cookie = jQuery.trim(cookies[i]);
        // Does this cookie string begin with the name we want?
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
      }
    return cookieValue;
  }

  $('.moder-line a[action-class]').click(function(e) {
    e.preventDefault();
    var moderLine = $(e.target).closest('.moder-line');
    var moderFrame = moderLine.find('.moder-frame');
    if (moderFrame.length !== 0) {
      moderFrame.empty();
    } else {
      moderFrame = $('<div class="moder-frame"></div>');
      moderFrame.appendTo(moderLine);
    }
    moderFrame.html('\\-/|\\-/|\\-/|\\-/|\\-/|\\-/|\\-/');

    function sendRequest(object, state, form, action) {
      object = object || {};
      state = state || {};
      form = form || {};
      action = action || {};
      var csrfmiddlewaretoken = GetCookie('csrftoken');
      var request = {
        object: object,
        state: state,
        form: form,
        action: action
      };
      var req = $.ajax({
        url: '/json/action/',
        type: 'POST',
        data: {csrfmiddlewaretoken: csrfmiddlewaretoken,
               request: JSON.stringify(request)},
        cache: false,
        dataType: 'json'
      }).done(function(data) {
        if (data.error) {
          moderFrame.html("Ошибка: " + data.error);
        } else if (data.content) {         
          moderFrame.html(data.content);

          moderFrame.find('button[action-action]').click(function(g) {
            var form = {};
            if (moderFrame.find('form')) {
              moderFrame.find('form').serializeArray().forEach(function(x) {
                form[x.name] = x.value;
              });
            }
            moderFrame.find('button[action-action]').attr('disabled', '1');
            sendRequest(data.object, data.state,
                        form, $(g.target).attr('action-action'));
          });
        } else {
          moderFrame.remove();
        }
      }).fail(function(xhr, textstatus){
        moderFrame.html("Ошибка: " + textstatus);
      });
    }

    var object = $(e.target).attr('action-object');
    if (object) {
      object = parseInt(object);
    }

    sendRequest({
      ctx: $(e.target).attr('action-context'),
      cls: $(e.target).attr('action-class'),
      obj: object});
  });
});

