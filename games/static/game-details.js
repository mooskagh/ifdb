$(function() {
  'use strict';

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

  $('#reply-1 textarea').focus(function() {
    $('#reply-2').hide();
    $('#reply-1 input').show();
    $('#reply-1 label').show();
    $('#reply-1 textarea').addClass('active');
  });

  $('.comment-box .reply-link').click(function() {
    var reply = $('#reply-2');
    var target = $(this).closest('.comment-box');
    if (target != reply.closest('.comment-box')) {
      reply.find('[name="parent"]').val(target.attr('data-id'));
      reply.find('textarea').val('');
      target.append(reply);
      reply.show();
    }

    $('#reply-1 input').hide();
    $('#reply-1 label').hide();
    $('#reply-1 textarea').removeClass('active');
    reply.find('textarea').focus();
    return false;
  });

  function setUpLikes(parent) {
    $(parent).find('a').click(function(e) {
      var id = $(this).closest('.comment-box').attr('data-id');
      $.ajax({
        type: 'POST',
        url: '/json/commentvote/',
        data: {
          'comment': id,
          'cur_val': $(this).attr('like-value'),
          'csrfmiddlewaretoken': GetCookie('csrftoken')
        },
        success: function(data) {
          $(parent).html(data);
          setUpLikes(parent);
        }
      });
      return false;
    });
  }

  $('.comment-box .likes').each(function() {
    setUpLikes(this);
  });

  if ($.fn.slick !== undefined) {
    $('.largeslider').slick({
      slidesToShow: 1,
      slidesToScroll: 1,
      centerMode: true,
      fade: true,
      asNavFor: '.smallslider'
    });

    $('.smallslider').slick({
      slidesToScroll: 1,
      dots: true,
      centerMode: true,
      focusOnSelect: true,
      variableWidth: true,
      infinite: false,
      asNavFor: '.largeslider'
    });
  }
});