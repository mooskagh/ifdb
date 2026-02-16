$(function () {
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

  $('#reply-1 textarea').focus(function () {
    $('#reply-2').hide();
    $('#reply-1 input').show();
    $('#reply-1 label').show();
    $('#reply-1 textarea').addClass('active');
  });

  $('.comment-box .reply-link').click(function () {
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
    $(parent).find('a').click(function (e) {
      var id = $(this).closest('.comment-box').attr('data-id');
      $.ajax({
        type: 'POST',
        url: '/json/commentvote/',
        data: {
          'comment': id,
          'cur_val': $(this).attr('like-value'),
          'csrfmiddlewaretoken': GetCookie('csrftoken')
        },
        success: function (data) {
          $(parent).html(data);
          setUpLikes(parent);
        }
      });
      return false;
    });
  }

  $('.comment-box .likes').each(function () {
    setUpLikes(this);
  });
});

// The rest is vanilla js rather than jQuery

let initGallery = () => {
  let images = document.querySelectorAll('#gallery-thumbs img');
  let main = document.getElementById('gallery-main');

  let selectImg = (img) => {
    main.innerHTML = '';
    let content = null;
    if (img.hasAttribute('iframe-url')) {
      content = document.createElement('iframe');
      content.src = img.getAttribute('iframe-url');
      content.style.width = '600px';
      content.style.height = '360px';
      content.setAttribute('frameborder', '0');
      content.setAttribute('marginwidth', '0');
    } else {
      let link = document.createElement('a');
      link.className = 'gallery--image-link';
      link.target = '_blank';
      link.href = img.src;
      content = document.createElement('img');
      content.src = img.src;
      link.appendChild(content);
      content = link;
    }
    document.getElementById('gallery-caption').innerText = img.getAttribute('alt');
    main.appendChild(content);

    let images = document.querySelectorAll('#gallery-thumbs img');
    images.forEach(image => {image.classList.remove('slideritem-selected'); });
    img.classList.add('slideritem-selected');
  }

  if (images.length == 1) {
    document.getElementById('gallery-thumbs').style.display = 'none';
  } else {
    images.forEach(img => {
      if (img.hasAttribute('is-video')) {
        let div = document.createElement('div');
        img.replaceWith(div);
        div.className = 'videothumb slideritem';
        let h2 = document.createElement('h2');
        h2.innerHTML = '&#9654;';
        div.appendChild(img);
        div.appendChild(h2);
        div.onclick = () => selectImg(img);
      } else {
        img.className = 'slideritem';
        img.onclick = () => selectImg(img);
      }
    });
  }
  selectImg(images[0]);
};